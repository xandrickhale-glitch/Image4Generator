# streamlit_app.py
# Imagen 4 Generator — Gemini API (no billing, no JSON)
# Fitur:
# - Import guard (jelas jika SDK/namespace bermasalah)
# - Outline tipis antar bagian (container border=True)
# - Prompt Doctor (enhancer) sesuai kaidah Imagen 4
# - Gallery persisten (download tidak menghilangkan hasil)
# - Model: imagen-4.0-generate-preview-06-06 & imagen-4.0-ultra-generate-preview-06-06

import os
import io
import pkgutil

import streamlit as st

st.set_page_config(page_title="Imagen 4", page_icon="🎨", layout="wide")
st.title("🎨 Imagen 4 — Gemini)")

# ---------------------------
# Import Guard (anti-ImportError)
# ---------------------------
problems = []

# 1) Cek konflik nama lokal 'google'
if os.path.exists("./google") or os.path.exists("./google.py"):
    problems.append(
        "Ada folder/file bernama **`google`** di repo. Rename (mis. `gutils/`)."
    )

# 2) Deteksi paket pip 'google' yang menimpa namespace
has_bad_google = False
try:
    import google as _g  # type: ignore
    # Jika ada __file__, biasanya ini paket 'google' lama yang men-shadow namespace package
    if getattr(_g, "__file__", None):
        has_bad_google = True
except Exception:
    # kalau import gagal di sini, biarkan guard berikutnya yang menangani
    pass

if has_bad_google:
    problems.append(
        "Terpasang paket pip **`google`** (bukan SDK resmi). Hapus dari requirements dan rebuild."
    )

# 3) Coba import google.genai untuk pastikan SDK terpasang
_has_genai = True
try:
    from google import genai as _test_genai  # type: ignore
    del _test_genai
except Exception:
    _has_genai = False

if not _has_genai:
    problems.append(
        "Paket **`google-genai`** belum terpasang di environment. "
        "Pastikan `requirements.txt` berisi `google-genai>=1.29.0,<2.0.0` lalu Clear cache + Restart."
    )

if problems:
    with st.container(border=True):
        st.error("Gagal import `google.genai` karena masalah environment:")
        for p in problems:
            st.markdown(f"- {p}")
        st.markdown(
            "Langkah pemulihan cepat:\n"
            "1) Hapus paket `google` dari requirements (jika ada)\n"
            "2) Tambah `google-genai>=1.29.0,<2.0.0`\n"
            "3) Pastikan tidak ada folder/file bernama `google` di repo\n"
            "4) Clear cache + Restart app"
        )
    st.stop()

# Aman: import SDK resmi
from google import genai  # type: ignore
from google.genai import types  # type: ignore
st.caption("✅ google-genai import OK — siap generate")

# ---------------------------
# Session State (persist hasil)
# ---------------------------
if "gallery" not in st.session_state:
    st.session_state.gallery = []     # list of {"bytes":..., "fname": ...}
if "gen_id" not in st.session_state:
    st.session_state.gen_id = 0
if "enhanced_preview" not in st.session_state:
    st.session_state.enhanced_preview = ""

# ---------------------------
# Helper: Aspect phrase + Prompt enhancer
# ---------------------------
def aspect_phrase(ar: str) -> str:
    return {
        "16:9": "wide 16:9 composition",
        "9:16": "vertical 9:16 composition",
        "4:3": "classic 4:3 composition",
        "3:4": "vertical 3:4 composition",
        "1:1": "square composition",
    }.get(ar, "")

def enhance_prompt(
    base: str,
    preset: str,
    medium: str,
    style: str,
    lighting: str,
    composition: str,
    color: str,
    mood: str,
    quality: str,
    camera_lens_mm: str,
    camera_aperture: str,
    ar_text: str,
    safe_person_phrase: bool
) -> str:
    parts = []
    if base.strip():
        parts.append(base.strip())

    # Preset bundle
    if preset == "Cinematic":
        parts += ["cinematic look", "dramatic lighting", "rich contrast", "filmic color grading"]
    elif preset == "Studio Portrait":
        parts += ["studio portrait", "soft key light", "subtle rim light", "seamless backdrop"]
    elif preset == "Product Shot":
        parts += ["product photography", "clean background", "soft shadow", "commercial lighting"]
    elif preset == "Illustration":
        parts += ["highly detailed illustration", "clean linework", "balanced shading"]
    elif preset == "3D Render":
        parts += ["ultra-detailed 3D render", "physically based rendering", "global illumination"]

    # Medium
    if medium == "Photo":
        parts += ["photograph", "realistic details", "sharp focus"]
    elif medium == "Illustration":
        parts += ["illustration", "hand-drawn feel"]
    elif medium == "3D Render":
        parts += ["3D render", "ray tracing aesthetics"]

    # User fields
    for x in [style, lighting, composition, color, mood, quality, ar_text]:
        if x and x != "None":
            parts.append(x)

    # Camera (for Photo)
    if medium == "Photo":
        cam_bits = []
        if camera_lens_mm.strip():
            cam_bits.append(f"{camera_lens_mm.strip()}mm lens")
        if camera_aperture.strip():
            cam_bits.append(f"{camera_aperture.strip()} aperture")
        if cam_bits:
            parts.append(", ".join(cam_bits))

    if safe_person_phrase:
        parts.append("non-celebrity adult person")

    # Dedup sambil menjaga urutan
    seen, clean = set(), []
    for p in parts:
        p = p.strip().strip(",")
        if p and p not in seen:
            clean.append(p); seen.add(p)
    return ", ".join(clean)

# ---------------------------
# Sidebar: API & Config (outlined)
# ---------------------------
with st.sidebar:
    st.header("🔑 API & Model")
    with st.container(border=True):
        api_key_env = os.getenv("GEMINI_API_KEY", "")
        api_key = st.text_input("API Key (atau pakai ENV GEMINI_API_KEY)", value="", type="password")
        use_key = (api_key or api_key_env).strip()

        model_id = st.selectbox(
            "Model (Imagen 4 via Gemini API)",
            [
                "imagen-4.0-generate-preview-06-06",      # 1–4 images
                "imagen-4.0-ultra-generate-preview-06-06" # 1 image
            ],
            index=0
        )

    st.header("⚙️ Konfigurasi")
    with st.container(border=True):
        aspect = st.selectbox("Aspect ratio", ["1:1","3:4","4:3","16:9","9:16"], index=0)
        people = st.selectbox("People generation", ["dont_allow","allow_adult","allow_all"], index=1)
        max_imgs = 1 if "ultra-generate" in model_id else 4
        num_images = st.selectbox(
            "Jumlah gambar",
            options=list(range(1, max_imgs + 1)),
            index=(max_imgs - 1)
        )

# ---------------------------
# Original Prompt (outlined)
# ---------------------------
with st.container(border=True):
    st.subheader("🧾 Original Prompt")
    prompt = st.text_area(
        "English prompt (recommended for Imagen 4)",
        placeholder=(
            "A photorealistic macro shot of a dew-covered leaf at sunrise, "
            "ultra-detailed, crisp, 4k"
        ),
        key="orig_prompt"
    )

# ---------------------------
# Prompt Doctor / Enhancer (outlined)
# ---------------------------
with st.container(border=True):
    st.subheader("✨ Prompt Doctor — Imagen 4 style")

    c1, c2, c3, c4 = st.columns([1,1,1,1])
    with c1:
        preset = st.selectbox("Preset", ["Cinematic","Studio Portrait","Product Shot","Illustration","3D Render","None"], index=0)
        medium = st.selectbox("Medium", ["Photo","Illustration","3D Render"], index=0)
    with c2:
        style = st.text_input("Style keywords", "dramatic, realistic")
        lighting = st.text_input("Lighting", "soft light, volumetric glow")
    with c3:
        composition = st.text_input("Composition", "rule of thirds, leading lines")
        color = st.text_input("Color palette", "rich, warm tones")
    with c4:
        mood = st.text_input("Mood", "serene, cinematic")
        quality = st.text_input("Quality", "highly detailed, crisp, 8k uhd")

    c5, c6, c7 = st.columns([1,1,1])
    with c5:
        lens_mm = st.text_input("Lens (photo only)", "50")
    with c6:
        aperture = st.text_input("Aperture (photo only)", "f/1.8")
    with c7:
        safe_person = st.checkbox("Add safe person phrase", value=False, help="Adds 'non-celebrity adult person'")

    col_enh_a, col_enh_b = st.columns([1,3])
    with col_enh_a:
        if st.button("⚡ Enhance"):
            st.session_state.enhanced_preview = enhance_prompt(
                base=prompt,
                preset=preset,
                medium=medium,
                style=style,
                lighting=lighting,
                composition=composition,
                color=color,
                mood=mood,
                quality=quality,
                camera_lens_mm=lens_mm,
                camera_aperture=aperture,
                ar_text=aspect_phrase(aspect),
                safe_person_phrase=safe_person,
            )
    with col_enh_b:
        use_enhanced = st.checkbox("Use Enhanced Prompt for Generation", value=True)

    st.text_area(
        "Enhanced Prompt (preview / copy)",
        value=st.session_state.enhanced_preview,
        height=120,
        key="enh_prev",
        label_visibility="visible"
    )

# ---------------------------
# Actions (outlined)
# ---------------------------
with st.container(border=True):
    st.subheader("🚀 Generate & Manage")
    col_a, col_b, col_c = st.columns([1,1,1])
    with col_a:
        do_gen = st.button("Generate")
    with col_b:
        clear_btn = st.button("Clear Gallery")
    with col_c:
        st.write("")

if clear_btn:
    st.session_state.gallery = []
    st.rerun()

# ---------------------------
# Generate
# ---------------------------
if do_gen:
    if not use_key:
        st.error("Masukkan API key atau set ENV `GEMINI_API_KEY` terlebih dulu.")
        st.stop()

    try:
        client = genai.Client(api_key=use_key)

        effective_prompt = (
            st.session_state.enhanced_preview.strip()
            if use_enhanced and st.session_state.enhanced_preview.strip()
            else (prompt or "").strip()
        )
        if not effective_prompt:
            st.error("Prompt belum diisi.")
            st.stop()

        st.info(f"Using prompt: {effective_prompt}")

        resp = client.models.generate_images(
            model=model_id,
            prompt=effective_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=int(num_images),
                aspect_ratio=aspect,
                person_generation=people
            )
        )

        generated = getattr(resp, "generated_images", []) or []
        if not generated:
            st.warning("Tidak ada gambar (mungkin diblokir safety atau kuota habis).")
        else:
            st.session_state.gen_id += 1
            gen_id = st.session_state.gen_id
            st.session_state.gallery = []
            for i, g in enumerate(generated, start=1):
                img_bytes = g.image.image_bytes  # PNG by default (SDK)
                fname = f"{model_id}_gen{gen_id}_{i}.png"
                st.session_state.gallery.append({"bytes": img_bytes, "fname": fname})

    except Exception as e:
        st.error(f"Gagal generate: {e}")
        st.info("Cek: model ID valid, rate limit, dan apakah Generative Language API sudah di-enable.")

# ---------------------------
# Results (outlined)
# ---------------------------
with st.container(border=True):
    st.subheader("🖼️ Results")
    if st.session_state.gallery:
        cols = st.columns(2)
        for i, item in enumerate(st.session_state.gallery):
            with cols[i % 2]:
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(item["bytes"]))
                    st.image(img, caption=item["fname"], use_column_width=True)
                except Exception:
                    st.error(f"Gagal pratinjau: {item['fname']}")
                st.download_button(
                    "💾 Download",
                    data=item["bytes"],
                    file_name=item["fname"],
                    mime="image/png",
                    key=f"dl_{st.session_state.gen_id}_{i}"  # unik per sesi + index
                )
    else:
        st.caption("Belum ada hasil. Generate dulu ya.")
