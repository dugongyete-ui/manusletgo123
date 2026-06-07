# System Prompt Recipes for Image Generation

Dokumen ini berisi kumpulan "resep" prompt sistem yang digunakan oleh Manus untuk menghasilkan gambar yang berkualitas tinggi dan sesuai dengan kebutuhan pengguna. Setiap resep dirancang untuk skenario spesifik.

## Pola Prompt Umum (General Prompt Pattern)

Gunakan struktur ini sebagai dasar untuk hampir semua permintaan pembuatan gambar:

```text
Create [image type] for [specific use case].
Subject: [main subject with necessary visual details].
Composition: [aspect ratio, framing, focal point, safe area, background relationship].
Style: [photographic/vector/3D/editorial/pixel/etc.], [lighting], [palette], [mood].
Constraints: [transparent background/text/no text/brand colors/reference matching/format needs].
Avoid: [scenario-specific errors that would make the image unusable].
```

---

## Resep Skenario Spesifik

### 1. Website Hero Image
Digunakan untuk landing page, situs SaaS, dan header produk.
- **Fokus:** Ruang negatif untuk teks (negative space), komposisi landscape lebar, dan gaya visual yang modern.

### 2. Product Commercial Visual
Digunakan untuk render produk, gambar e-commerce, dan visual peluncuran produk.
- **Fokus:** Akurasi bentuk/material produk, pencahayaan studio, dan latar belakang yang bersih.

### 3. Social Campaign / Poster
Digunakan untuk iklan, poster acara, dan thumbnail media sosial.
- **Fokus:** Titik fokus tunggal yang kuat, hierarki teks yang jelas, dan keterbacaan pada ukuran kecil.

### 4. UI Mockup
Digunakan untuk tampilan aplikasi, dashboard, dan antarmuka produk.
- **Fokus:** Grid yang bersih, spasi realistis, navigasi jelas, dan label yang masuk akal (plausible).

### 5. Logo Concept
Digunakan untuk eksplorasi tanda merek dan ikon aplikasi.
- **Fokus:** Simbolisme sederhana, skalabilitas, dan siluet yang jelas.

### 6. Game Asset
Digunakan untuk properti (props), sprite, karakter, dan tile game.
- **Fokus:** Sudut pandang konsisten (misal: isometric/top-down), latar belakang transparan, dan pencahayaan yang konsisten.

### 7. Character Consistency
Digunakan untuk potret, maskot, dan karakter berulang.
- **Fokus:** Jangkar identitas (usia, bentuk wajah, pakaian, aksesoris) yang harus dipertahankan.

### 8. Image Upscale / Restore
Digunakan khusus untuk meningkatkan resolusi tanpa mengubah konten.
- **Prompt Khusus:** `Restore and upscale this image to high resolution while preserving every detail exactly as in the original.`

### 9. Precise Image Edit
Digunakan untuk mengubah bagian tertentu dari gambar yang sudah ada.
- **Fokus:** Hanya mengubah target yang diminta dan menjaga area lainnya (pose, pencahayaan, gaya) tetap sama.

---

## Panduan Penulisan Teks dalam Gambar

Manus diinstruksikan untuk merender teks (termasuk bahasa Mandarin, Inggris, Indonesia, dll.) secara langsung di dalam gambar. Jangan membuat latar belakang kosong lalu menimpa teks secara terpisah menggunakan kode, kecuali jika pengguna secara eksplisit meminta file sumber yang dapat diedit (seperti HTML/CSS).

### Cara Mengatur Konten Teks:
1. Atur teks ke dalam blok: Judul, Subjudul, Bagian, Label, CTA.
2. Pertahankan nama produk, harga, tanggal, dan istilah teknis dengan tepat.
3. Hindari teks yang terlalu padat yang dapat merusak estetika visual.
