# =============================================================================
# Imagen 4 Generator — Gemini API (Qwiklabs, no billing, no JSON)
# -----------------------------------------------------------------------------
# Fitur:
# - Import guard: mendeteksi environment bermasalah (paket 'google' salah, SDK belum terpasang,
#   atau ada folder/file lokal bernama 'google') lalu berhenti dengan pesan jelas di UI.
# - Outline tipis via st.container(border=True).
# - Prompt Doctor (enhancer) untuk menyusun prompt yang rapi sesuai kaidah Imagen 4.
# - Gallery persisten (download tidak menghapus hasil), key unik per tombol.
# - Model: imagen-4.0-generate-preview-06-06 (1–4), imagen-4.0-ultra-generate-preview-06-06 (1).
# - Ekspor ZIP seluruh hasil + pilih output PNG/JPEG (konversi dengan PIL).
# - History: menyimpan riwayat prompt & konfigurasi.
# =============================================================================

import os
import io
import zipfile
import importlib
from typing import List, Dict, Any

import streamlit as st
from PIL import Image

# ---------------------------
# Konfigurasi halaman
# ---------------------------
st.set_page_config(page_title="Imagen 4 Generator", page_icon="🎨", layout="wide")
st.title("🎨 Imagen 4 — Gemini")

# ---------------------------
# IMPORT GUARD (WAJIB di paling atas, sebelum import SDK)
# ---------------------------
def environment_guard() -> List[str]:
    """Cek masalah umum yang bikin `google.genai` gagal diimpor."""
    problems: List[str] = []

    # 1) Cek konflik nama lokal 'google'
    if os.path.exists("./google") or os.path.exists("./google.py"):
        problems.append("Ada folder/file bernama **`google`** di repo. Rename (mis. `gutils/`).")

    # 2) Cek paket pip 'google' (menimpa namespace package PEP 420)
    bad_google = False
    try:
        import google as _g  # noqa: F401
        # Jika punya __file__ fisik, seringnya itu paket 'google' yang tidak kompatibel
        if getattr(_g, "__file__", None):
            bad_google = True
    except Exception:
        # Jika gagal import di sini, tidak serta-merta masalah; lanjut cek SDK
        pass
    if bad_google:
        problems.append("Terpasang paket pip **`google`**. Hapus dari requirements dan rebuild (gunakan **google-genai** saja).")

    # 3) Cek ketersediaan modul google.genai (SDK)
    if importlib.util.find_spec("google.genai") is None:
        problems.append("SDK **`google-genai`** belum terpasang. Tambah `google-genai>=1.29.0,<2.0.0` di requirements.txt, lalu Clear cache + Restart.")

    return problems

_guard_issues = environment_guard()
if _guard_issues:
    with st.container(border=True):
        st.error("Gagal import `google.genai` karena masalah environment:")
        for p in _guard_issues:
            st.markdown(f"- {p}")
        st.markdown("Perbaiki lalu **Manage app → Clear cache → Restart**.")
    st.stop()

# ✅ Import SDK via importlib (bukan `from google import genai`)
genai = importlib.import_module("google.genai")
types = importlib.import_module("google.genai.types")
try:
    import importlib.metadata as md
    st.caption(f"SDK OK · google-genai {md.version('google-genai')}")
except Exception:
    st.caption("SDK OK · google-genai terpasang")

# ---------------------------
# STATE (persist di session)
# ---------------------------
if "gallery" not in st.session_state:
    st.session_state.gallery: List[Dict[str, Any]] = []   # [{"bytes": b"...", "fname": "...", "format": "PNG"}]
if "gen_id" not in st.session_state:
    st.session_state.gen_id = 0
if "enhanced_preview" not in st.session_state:
    st.session_state.enhanced_preview = ""
if "history" not in st.session_state:
    st.session_state.history: List[Dict[str, Any]] = []   # simpan riwayat generate

# ---------------------------
# Helper: Aspect phrase & Prompt enhancer
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
    parts: List[str] = []
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

    # Camera (Photo only)
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

def convert_bytes(img_bytes: bytes, out_format: str = "PNG") -> bytes:
    """Konversi PNG bytes → PNG/JPEG sesuai pilihan. JPEG: pastikan RGB (tanpa alpha)."""
    out_format = out_format.upper()
    if out_format not in ("PNG", "JPEG"):
        return img_bytes  # fallback
    try:
        im = Image.open(io.BytesIO(img_bytes))
        buf = io.BytesIO()
        if out_format == "JPEG":
            if im.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
        im.save(buf, format=out_format, quality=95 if out_format == "JPEG" else None)
        return buf.getvalue()
    except Exception:
        # Jika gagal konversi, kembalikan asli
        return img_bytes

def zip_gallery(items: List[Dict[str, Any]]) -> bytes:
    """Buat ZIP in-memory dari semua item gallery."""
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for it in items:
            zf.writestr(it["fname"], it["bytes"])
    mem.seek(0)
    return mem.getvalue()

# ---------------------------
# Sidebar: API & Config
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
        num_images = st.selectbox("Jumlah gambar", options=list(range(1, max_imgs + 1)), index=(max_imgs - 1))
        out_fmt = st.selectbox("Output format", ["PNG","JPEG"], index=0)

# ---------------------------
# Original Prompt
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
# Prompt Doctor (Enhancer)
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
# Actions
# ---------------------------
with st.container(border=True):
    st.subheader("🚀 Generate & Manage")
    col_a, col_b, col_c, col_d = st.columns([1,1,1,1])
    with col_a:
        do_gen = st.button("Generate")
    with col_b:
        clear_btn = st.button("Clear Gallery")
    with col_c:
        zip_all = st.button("Download ZIP (All)")
    with col_d:
        show_diag = st.checkbox("Show Diagnostics", value=False)

if clear_btn:
    st.session_state.gallery.clear()
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
            # simpan hasil ke gallery (dengan konversi format bila dipilih)
            st.session_state.gen_id += 1
            gen_id = st.session_state.gen_id
            st.session_state.gallery = []
            for i, g in enumerate(generated, start=1):
                raw = g.image.image_bytes  # default PNG
                final_bytes = convert_bytes(raw, out_fmt)
                fname = f"{model_id}_gen{gen_id}_{i}.{out_fmt.lower()}"
                st.session_state.gallery.append({"bytes": final_bytes, "fname": fname, "format": out_fmt})

            # simpan history
            st.session_state.history.append({
                "gen_id": gen_id,
                "model": model_id,
                "prompt_used": effective_prompt,
                "aspect": aspect,
                "people": people,
                "num_images": int(num_images),
                "format": out_fmt
            })

    except Exception as e:
        msg = str(e)
        st.error(f"Gagal generate: {msg}")
        if "429" in msg or "quota" in msg.lower() or "Rate" in msg:
            st.info("Kamu mungkin terkena rate limit/kuota free tier. Coba kurangi request atau tunggu beberapa saat.")

# ---------------------------
# Results
# ---------------------------
with st.container(border=True):
    st.subheader("🖼️ Results")
    if st.session_state.gallery:
        # Download ZIP semua
        if zip_all:
            zbytes = zip_gallery(st.session_state.gallery)
            st.download_button("💾 Download ZIP Now", data=zbytes, file_name="imagen4_outputs.zip", type="primary")

        cols = st.columns(2)
        for i, item in enumerate(st.session_state.gallery):
            with cols[i % 2]:
                try:
                    im = Image.open(io.BytesIO(item["bytes"]))
                    st.image(im, caption=item["fname"], use_column_width=True)
                except Exception:
                    st.error(f"Gagal pratinjau: {item['fname']}")
                st.download_button(
                    "⬇️ Download",
                    data=item["bytes"],
                    file_name=item["fname"],
                    mime=f"image/{item.get('format','PNG').lower()}",
                    key=f"dl_{st.session_state.gen_id}_{i}"
                )
    else:
        st.caption("Belum ada hasil. Generate dulu ya.")

# ---------------------------
# History & Diagnostics
# ---------------------------
with st.container(border=True):
    st.subheader("🧭 History & Diagnostics")
    if st.session_state.history:
        for h in reversed(st.session_state.history[-10:]):  # tampilkan 10 terakhir
            with st.expander(f"gen_id={h['gen_id']} · {h['model']} · {h['num_images']} img · {h['format']}"):
                st.write(f"**Prompt:** {h['prompt_used']}")
                st.write(f"Aspect: {h['aspect']} · People: {h['people']}")
    else:
        st.caption("Belum ada history.")

    if show_diag:
        with st.expander("Diagnostics"):
            st.write("Environment variables penting:")
            st.code({k: os.getenv(k, "") for k in ["GEMINI_API_KEY"]})
            st.write("Model aktif & konfigurasi:")
            st.code({
                "model_id": model_id,
                "aspect": aspect,
                "people": people,
                "num_images": int(num_images),
                "out_fmt": out_fmt
            })
