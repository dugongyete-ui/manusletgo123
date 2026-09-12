---
name: web-recon-endpoint-finder
description: Metodologi reverse-engineering website — untuk menemukan endpoint API tersembunyi, mekanisme auth, struktur data, dan cara mengintegrasikan layanan web apapun (bukan hanya AI). Gunakan ketika user ingin "cari endpoint website ini", "reverse engineer", "scrape API", "integrasi tanpa SDK resmi", "cari cara akses data dari website X", "recon website", "analisa API website", "temukan endpoint tersembunyi", "bypass API", "inspect API", "cek auth mechanism", atau "cara ambil data dari website". Juga trigger ketika user memberi URL dan minta cari API, endpoint, atau cara akses data dari URL tersebut.
---

# Web Recon & Endpoint Finder

Metodologi ini terinspirasi dari pendekatan gpt4free namun **berlaku untuk semua jenis website** — e-commerce, media sosial, berita, fintech, travel, AI, SaaS, dan lainnya. Tujuannya: menemukan bagaimana sebuah website berkomunikasi dengan backend-nya, lalu mereplikasi komunikasi tersebut secara programatik.

---

## ⚠️ ATURAN WAJIB

1. **Hanya untuk tujuan legal** — scraping/recon untuk riset, integrasi pribadi, atau reverse-engineering yang diizinkan ToS.
2. **Jangan bypass paywall berbayar** tanpa izin eksplisit pemilik layanan.
3. **Hormati rate limit** — jangan buat request berlebihan yang bisa membebani server target.
4. **Tidak untuk credential stuffing** atau akses akun orang lain.

---

## Alur Kerja (Urutan Wajib)

Ketika user memberikan URL target, jalankan fase-fase berikut secara **berurutan** menggunakan Bash tool. Laporkan hasil setiap fase ke user sebelum lanjut ke fase berikutnya. Jika user ingin hasil lengkap sekaligus, jalankan semua fase lalu berikan laporan komprehensif.

### FASE 1 — Profiling Awal Website

```bash
TARGET="https://target.com"

# 1. Cek headers server
rg -N '' "curl -s -I \"\$TARGET\"" <<< ''
curl -s -I "$TARGET" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36" \
  --max-time 10

# 2. Probe endpoint umum sekaligus
for ep in \
  "/api" "/api/v1" "/api/v2" "/v1" "/v2" \
  "/api/config" "/config.json" "/manifest.json" "/.well-known/openid-configuration" \
  "/graphql" "/gql" "/query" \
  "/api/auth" "/auth" "/login" "/api/login" "/api/session" \
  "/api/user" "/api/me" "/api/profile" \
  "/api/search" "/search" \
  "/api/data" "/data" \
  "/sitemap.xml" "/robots.txt" \
  "/swagger.json" "/openapi.json" "/api-docs" "/docs/api"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$TARGET$ep" \
    -H "User-Agent: Mozilla/5.0 Chrome/138.0.0.0" --max-time 8 2>/dev/null)
  [ "$code" != "404" ] && echo "$code  $ep"
done
```

**Interpretasi kode HTTP:**
| Kode | Arti | Tindakan |
|---|---|---|
| `200` | Terbuka | Test langsung |
| `401` | Ada, butuh auth | Cari token/session |
| `403` | Ada, diblokir | Coba bypass header |
| `404` | Tidak ada | Coba variasi path lain |
| `405` | Method salah | Ganti GET↔POST |
| `307/302` | Redirect | Follow redirect-nya |
| `429` | Rate limited | Tambah delay / rotasi IP |
| `500` | Server error | Endpoint ada tapi payload salah |

---

### FASE 2 — Identifikasi Tech Stack

```bash
TARGET="https://target.com"

# Dari headers HTTP
curl -sI "$TARGET" | grep -iE "server|x-powered-by|x-framework|cf-ray|x-vercel|x-amz"

# Dari HTML meta tags
curl -s "$TARGET" | grep -iE '<meta[^>]+(generator|framework|version)[^>]+>'

# Dari robots.txt
curl -s "$TARGET/robots.txt"

# Dari HTML — cari link ke JS bundle
curl -s "$TARGET" | grep -oE 'src="[^"]+\.(js|mjs)"' | head -10
curl -s "$TARGET" | grep -oE "src='[^']+\.(js|mjs)'" | head -10

# Dari HTML — cari link API/backend hints
curl -s "$TARGET" | grep -oE '"(https?://[^"]{0,100}api[^"]{0,100})"' | sort -u | head -20
```

**Tanda-tanda tech stack:**
- `x-powered-by: Next.js` → Next.js, cek `/_next/static/` dan `__NEXT_DATA__`
- `x-powered-by: Express` → Node.js Express
- `cf-ray` header → Cloudflare
- `x-vercel-id` → Vercel hosting
- `X-Amz-*` → AWS
- Nuxt.js → cek `__nuxt` di HTML
- Django → cek `/admin/`, CSRF token pattern

---

### FASE 3 — Ekstrak Endpoint dari Source JS

Teknik paling efektif untuk SPA (Single Page App).

```bash
TARGET="https://target.com"

# A. Dapatkan daftar JS bundle dari HTML
JS_FILES=$(curl -s "$TARGET" | grep -oE '"(/[^"']+\.(js|mjs))"' | tr -d '"' | sort -u)
echo "$JS_FILES"

# B. Cari endpoint dari setiap JS bundle (batas 5 bundle untuk hemat waktu)
for JS in $JS_FILES; do
  JS_URL="$TARGET$JS"
  echo "=== $JS_URL ==="

  # Cari semua path /api/... dan /v1/...
  curl -s "$JS_URL" --max-time 30 | grep -oE '"(/api[^"]{0,100})"' | sort -u | head -20
  curl -s "$JS_URL" --max-time 30 | grep -oE '"(/v[0-9][^"]{0,100})"' | sort -u | head -20

  # Cari fetch() dan axios calls
  curl -s "$JS_URL" --max-time 30 | grep -oE 'fetch\("([^"]{0,100})"\)' | head -15
  curl -s "$JS_URL" --max-time 30 | grep -oE "axios\.(get|post|put|delete)\(['\"]([^'\"]{0,100})" | head -15

  # Cari base URL variable
  curl -s "$JS_URL" --max-time 30 | grep -oE '(BASE_URL|API_URL|apiUrl|baseUrl|ENDPOINT)[^,;]{0,100}' | head -10

done
```

**Teknik tambahan untuk Next.js:**
```bash
# __NEXT_DATA__ di HTML
curl -s "$TARGET" | grep -oE '<script id="__NEXT_DATA__"[^>]*>([^<]+)<' | head -1

# Next.js API routes
for ep in "/api/auth/session" "/api/auth/providers" "/api/trpc" "/api/hello"; do
  curl -s -o /dev/null -w "%{http_code}  $ep\n" "$TARGET$ep" --max-time 5
done
```

---

### FASE 4 — Analisis dengan Browser DevTools (Panduan Manual)

Ketika curl tidak cukup, gunakan DevTools browser:

```
1. Buka website target di Chrome/Firefox
2. F12 → tab "Network"
3. Filter: "Fetch/XHR" (untuk API calls saja)
4. Lakukan aksi: search, login, scroll, klik tombol
5. Klik request → Headers, Payload, Response
6. Klik kanan → "Copy as cURL" untuk replay

Untuk GraphQL:
- Filter "graphql" di Network tab
- Lihat Payload → operationName, query, variables

Untuk WebSocket:
- Filter "WS" → lihat Messages
```

---

### FASE 5 — Mekanisme Auth

#### A. Session/Cookie
```bash
curl -s -c /tmp/cookies.txt -X POST "$TARGET/api/login" \
  -H "Content-Type: application/json" \
  -H "User-Agent: Mozilla/5.0 Chrome/138.0.0.0" \
  -d '{"email":"user@example.com","password":"password123"}'

curl -s -b /tmp/cookies.txt "$TARGET/api/protected-resource" \
  -H "User-Agent: Mozilla/5.0 Chrome/138.0.0.0"
```

#### B. Bearer Token (JWT)
```bash
TOKEN=$(curl -s -X POST "$TARGET/api/auth/signin" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass"}' \
  | grep -oE '"token":"([^"]+)"' | cut -d'"' -f4)

echo "Token: $TOKEN"
echo "$TOKEN" | cut -d'.' -f2 | base64 -d 2>/dev/null | python3 -m json.tool

curl -s "$TARGET/api/user/profile" -H "Authorization: Bearer $TOKEN"
```

#### C. Guest/Anonymous
```bash
curl -s "$TARGET/api/session" \
  -H "User-Agent: Mozilla/5.0 Chrome/138.0.0.0" \
  -H "Accept: application/json"

# Atau via guest login
curl -s -X POST "$TARGET/api/auth/guest" \
  -H "Content-Type: application/json" -d '{}'
```

#### D. OAuth / SSO
```bash
curl -s "$TARGET/.well-known/openid-configuration" | python3 -m json.tool
curl -s "$TARGET/login" | grep -oE 'https://[^"]+oauth[^"]+' | head -5
```

#### E. API Key di Header
```bash
curl -s "JS_BUNDLE_URL" | grep -oE '(x-api-key|apikey|api_key|X-Client-ID)[^,;]{0,80}' | head -10
curl -s "$TARGET/api/endpoint" -H "X-API-Key: KEY_DARI_JS_BUNDLE"
```

#### F. HMAC / Signature
```bash
curl -s "JS_BUNDLE_URL" | grep -oE '(hmac|HMAC|signature|sign)\([^)]{0,200}\)' | head -10
curl -s "JS_BUNDLE_URL" | grep -oE '"(secret|SECRET|key|KEY)":\s*"[^"]{10,64}"' | head -5
```

---

### FASE 6 — Analisis Format Request & Response

```bash
TOKEN="..."
COOKIE="session=abc123"

# GET
curl -s "$TARGET/api/endpoint" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: Mozilla/5.0 Chrome/138.0.0.0" \
  | python3 -m json.tool | head -50

# POST JSON
curl -s -X POST "$TARGET/api/endpoint" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "User-Agent: Mozilla/5.0 Chrome/138.0.0.0" \
  -d '{"key":"value"}' | python3 -m json.tool | head -50

# GraphQL
curl -s -X POST "$TARGET/graphql" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"operationName":"GetUser","query":"query GetUser { me { id name email } }","variables":{}}' \
  | python3 -m json.tool
```

---

### FASE 7 — Test Streaming Response

```bash
# SSE
curl -s -X POST "$TARGET/api/stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"test"}' --max-time 30 | head -30

# NDJSON
curl -s "$TARGET/api/live-feed" \
  -H "Authorization: Bearer $TOKEN" --max-time 10 | head -5 | python3 -m json.tool
```

---

### FASE 8 — Bypass Proteksi Umum

| Proteksi | Cara Bypass |
|---|---|
| **Cloudflare** | `--tlsv1.3` + Chrome User-Agent + Origin/Referer header |
| **Rate limiting** | Tambah delay `sleep 1`, rotasi UUID/session |
| **CORS** | Proxy server lokal (dari server, bukan browser) |
| **Captcha login** | Cari endpoint guest/anonim tanpa captcha |
| **X-Signature / HMAC** | Reverse-engineer dari JS bundle |
| **Hotlink protection** | Tambah `Referer: https://target.com/` + Chrome UA |
| **Token expiry** | Cache token + deteksi 401 → refresh otomatis |
| **User-Agent detection** | Chrome UA terbaru |
| **Anti-bot (bot score)** | Tambah `sec-ch-ua`, `sec-fetch-*`, `Accept-Language` |

**Header browser lengkap:**
```bash
curl -s "$TARGET/api/endpoint" \
  --tlsv1.3 \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36" \
  -H "Accept: application/json, text/plain, */*" \
  -H "Accept-Language: en-US,en;q=0.9" \
  -H "Accept-Encoding: gzip, deflate, br" \
  -H "Origin: https://target.com" \
  -H "Referer: https://target.com/" \
  -H "Sec-Ch-Ua: \"Chromium\";v=\"138\", \"Google Chrome\";v=\"138\"" \
  -H "Sec-Ch-Ua-Mobile: ?0" \
  -H "Sec-Ch-Ua-Platform: \"Windows\"" \
  -H "Sec-Fetch-Dest: empty" \
  -H "Sec-Fetch-Mode: cors" \
  -H "Sec-Fetch-Site: same-origin" \
  -H "Connection: keep-alive"
```

---

### FASE 9 — Analisis GraphQL

```bash
TARGET="https://target.com"
TOKEN="..."

# 1. Introspection query
GQL_URLS=("$TARGET/graphql" "$TARGET/gql" "$TARGET/api/graphql")
for GQL in "${GQL_URLS[@]}"; do
  echo "=== Testing $GQL ==="
  curl -s -X POST "$GQL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"query":"{ __schema { types { name kind fields { name type { name kind ofType { name kind } } } } } }"}' \
    | python3 -m json.tool 2>/dev/null | head -30
  echo
  # Jika respons punya data, hentikan loop
  curl -s -X POST "$GQL" \
    -H "Content-Type: application/json" \
    -d '{"query":"{ __typename }"}' | grep -q '"data"' && break
done

# 2. Temukan semua Query
curl -s -X POST "$GQL" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __schema { queryType { fields { name description args { name type { name } } } } } }"}' \
  | python3 -m json.tool

# 3. Temukan semua Mutation
curl -s -X POST "$GQL" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __schema { mutationType { fields { name description } } } }"}' \
  | python3 -m json.tool
```

---

### FASE 10 — Dokumentasi Hasil Recon

Setelah selesai, dokumentasikan hasilnya dalam format ini:

```markdown
## Hasil Recon: target.com

### Tech Stack
- Frontend: ...
- Hosting: ...
- CDN: ...
- Backend: ...

### Auth Mechanism
- Tipe: ...
- Cara dapat token: ...
- Token TTL: ...
- Refresh: ...

### Endpoint Utama
| Endpoint | Method | Auth | Deskripsi |
|---|---|---|---|

### Format Request
- Content-Type: ...
- Wajib header: ...

### Format Response
- JSON structure: ...
- Pagination: ...

### Proteksi yang Ada
- ...

### Catatan Khusus
- ...
```

---

## Tips Penting

1. **Selalu mulai dari robots.txt dan sitemap.xml** — sering ada petunjuk path tersembunyi.
2. **Cek Network tab DevTools lebih dulu** dari curl — lebih cepat memahami flow auth.
3. **Copy as cURL dari DevTools** adalah cara tercepat mendapat request valid.
4. **Decode JWT** untuk pahami field dan TTL token.
5. **Gunakan `python3 -m json.tool`** untuk pretty-print JSON.
6. **Simpan cookie ke file** (`-c cookies.txt`) lalu reuse (`-b cookies.txt`).
7. **Perhatikan `X-Request-ID`** — beberapa server butuh UUID ini.
8. **Cari versi API** di JS bundle — `/v2/` mungkin tidak diumumkan tapi lebih stabil.
9. **Test payload minimal** dulu — tambah field satu per satu.
10. **Cek `X-RateLimit-*`** untuk tahu limit yang berlaku.

## Tools yang Berguna

```bash
# Pretty print JSON
echo '{"key":"val"}' | python3 -m json.tool

# Decode JWT
TOKEN="eyJ..."
echo "$TOKEN" | cut -d'.' -f2 | base64 -d 2>/dev/null

# Generate UUID
python3 -c "import uuid; print(uuid.uuid4())"

# URL encode
python3 -c "import urllib.parse; print(urllib.parse.quote('hello world'))"

# Extract cookies dari curl verbose
curl -v "https://target.com" 2>&1 | grep "Set-Cookie"

# Follow redirects
curl -sL -D - "https://target.com/api/redirect" -o /dev/null

# Test dengan timeout ketat
curl -s --max-time 5 --connect-timeout 3 "https://target.com/api/test"
```

## Cara Menggunakan Skill Ini

Ketika user meminta recon, ikuti alur ini:

1. **Minta URL target** jika belum diberikan
2. **Jalankan Fase 1** (Profiling) — laporkan headers & endpoint yang ditemukan
3. **Jalankan Fase 2** (Tech Stack) — identifikasi teknologi
4. **Jalankan Fase 3** (JS Endpoints) — ekstrak dari JS bundle
5. **Berdasarkan hasil**, tentukan fase selanjutnya yang relevan:
   - Jika ada endpoint auth → Fase 5 (Auth)
   - Jika ada GraphQL → Fase 9 (GraphQL)
   - Jika ada proteksi → Fase 8 (Bypass)
6. **Dokumentasikan** hasil akhir (Fase 10)
7. **Beri rekomendasi** cara mengintegrasikan / menggunakan endpoint yang ditemukan
