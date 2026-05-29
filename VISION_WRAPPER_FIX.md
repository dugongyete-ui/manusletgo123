# Fix: API Wrapper Harus Support Multimodal (Image) Request

## Konteks

Proyek AI agent **Dzeck** mengirim request ke endpoint wrapper kamu di:
```
https://divine-vittoria-dzeckyete-d2996f6e.koyeb.app/v1
```

Kode proyek sudah benar — upload gambar, encode base64, dan format request OpenAI multimodal semuanya sudah berjalan. **Masalahnya ada di sisi wrapper**: konten `image_url` dengan data base64 tidak diteruskan dengan benar ke model Qwen aslinya, dan model membalas dengan `[object Object]` atau "data object placeholder".

---

## Format Request yang Dikirim Proyek (Sudah Benar)

Proyek mengirim request `POST /v1/chat/completions` dengan format standar OpenAI multimodal:

```json
{
  "model": "qwen3.7-max",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "The user sent you these images as part of this request: What color is in this image?\n\nDescribe each image in detail..."
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA..."
          }
        }
      ]
    }
  ],
  "max_tokens": 4096,
  "temperature": 0.7
}
```

Catatan penting:
- Field `content` adalah **array**, bukan string
- Setiap elemen array punya field `type`: `"text"` atau `"image_url"`
- Gambar dikirim sebagai **base64 inline** dengan format: `data:{mime_type};base64,{data}`
- MIME type yang mungkin dikirim: `image/jpeg`, `image/jpg`, `image/png`, `image/gif`, `image/webp`

---

## Kemungkinan Penyebab Masalah di Wrapper

### Penyebab 1: Content array tidak diteruskan utuh
Banyak wrapper yang hanya mengambil teks pertama dari array content dan membuang sisanya:

```javascript
// SALAH — ini membuang gambar
const text = messages[0].content[0].text;
forwardToQwen({ content: text });

// BENAR — teruskan seluruh array content apa adanya
forwardToQwen({ content: messages[0].content });
```

### Penyebab 2: Serialisasi JSON tidak benar
Jika wrapper menggunakan concatenation string atau template literal untuk build JSON, objek nested bisa ter-serialize sebagai `[object Object]`:

```javascript
// SALAH
const body = `{"content": "${messages[0].content}"}`;
// Hasilnya: {"content": "[object Object]"}

// BENAR
const body = JSON.stringify({ content: messages[0].content });
```

### Penyebab 3: Content-Type tidak di-set dengan benar
Request ke Qwen API harus punya header:
```
Content-Type: application/json
```
Jika tidak, body JSON bisa salah terbaca.

### Penyebab 4: Payload di-transform/di-strip sebelum diteruskan
Beberapa wrapper men-transform payload untuk alasan logging, filtering, atau cost-control dan tidak menyertakan field gambar karena ukurannya besar.

---

## Yang Harus Diperbaiki di Wrapper

### Requirement Utama

Wrapper harus **meneruskan field `content` apa adanya** ke Qwen API tanpa modifikasi, baik itu string maupun array of objects.

### Contoh Implementasi Wrapper yang Benar (Node.js / Express)

```javascript
app.post('/v1/chat/completions', async (req, res) => {
  const payload = req.body;

  // JANGAN transform atau strip field content
  // Teruskan seluruh payload ke Qwen API
  const response = await fetch('https://api.qwen.ai/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${QWEN_API_KEY}`,
      'Content-Type': 'application/json',
    },
    // PENTING: JSON.stringify(payload) — jangan manual build JSON
    body: JSON.stringify(payload),
  });

  const data = await response.json();
  res.json(data);
});
```

### Contoh Implementasi Wrapper yang Benar (Python / FastAPI)

```python
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()

    # Teruskan payload utuh ke Qwen
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.qwen.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {QWEN_API_KEY}",
                "Content-Type": "application/json",
            },
            # PENTING: json=payload, bukan data=str(payload)
            json=payload,
            timeout=120,
        )
    
    return response.json()
```

---

## Cara Verifikasi Wrapper Sudah Benar

Kirim request test ini langsung ke wrapper kamu via curl:

```bash
curl -X POST https://divine-vittoria-dzeckyete-d2996f6e.koyeb.app/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <API_KEY_KAMU>" \
  -d '{
    "model": "qwen3.7-max",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "Gambar ini warnanya apa? Jawab satu kata saja."},
          {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADklEQVQI12P4z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=="}}
        ]
      }
    ],
    "max_tokens": 20
  }'
```

**Respons yang benar:** Model menyebut warna (misalnya "merah", "biru", "putih", dll.)

**Respons yang salah (masalah masih ada):**
- `[object Object]`
- "data object placeholder"
- "image was not successfully attached"
- "I cannot see any image"

---

## File Lain yang Sudah Bekerja dengan Baik (Tidak Perlu Diubah)

Semua tipe file berikut sudah **berhasil diproses di sisi server** tanpa melewati model vision, jadi tidak terpengaruh masalah wrapper ini:

| Tipe File | Cara Diproses |
|-----------|---------------|
| PDF | Ekstrak teks di server (pdfplumber) |
| DOCX / DOC | Ekstrak teks di server (python-docx) |
| XLSX / XLS | Ekstrak teks di server (pandas) |
| PPTX / PPT | Ekstrak teks di server (python-pptx) |
| CSV | Ekstrak teks di server |
| TXT / MD / PY / XML / HTML | Baca langsung sebagai teks |

Hanya file **gambar** (JPEG, PNG, GIF, WebP) yang melewati vision model dan membutuhkan perbaikan wrapper ini.

---

## Ringkasan Singkat untuk AI Agent

> **Masalah:** Wrapper API di Koyeb tidak meneruskan field `content` array (yang berisi gambar base64) dengan benar ke Qwen API. Objek nested di-serialize menjadi string `[object Object]` atau di-strip sebelum diteruskan.
>
> **Solusi:** Pastikan endpoint `/v1/chat/completions` di wrapper meneruskan seluruh field `messages[].content` apa adanya menggunakan `JSON.stringify(payload)` (Node.js) atau `json=payload` (Python httpx/requests) — **bukan** string concatenation atau manual serialization.
>
> **Test:** Kirim request multimodal dengan gambar base64 kecil dan verifikasi model menjawab dengan deskripsi warna/konten gambar, bukan error `[object Object]`.
