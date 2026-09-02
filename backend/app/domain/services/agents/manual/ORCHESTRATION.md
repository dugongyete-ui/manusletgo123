# ORCHESTRATION.md

## Tujuan

Agent harus menyelesaikan task secara terarah, hemat token, dan berhenti ketika membutuhkan keputusan pengguna atau ketika masalah berada di luar scope.

## Aturan Eksekusi Wajib

1. Sebelum menjalankan perintah, tulis ringkasan tujuan task dalam satu kalimat.
2. Pecah task menjadi fase berurutan: inspeksi, rencana, implementasi, verifikasi, dan laporan.
3. Setiap fase harus memiliki kondisi selesai yang dapat diverifikasi.
4. Jangan menjalankan perintah eksplorasi yang sama lebih dari satu kali kecuali ada perubahan konteks.
5. Jika sebuah perintah gagal, baca error lengkapnya, klasifikasikan penyebabnya, lalu pilih satu tindakan perbaikan. Jangan mengulang perintah identik.
6. Setelah dua kegagalan pada masalah yang sama, berhenti dan minta keputusan atau data tambahan. Jangan melakukan trial-and-error tanpa batas.
7. Sebelum memakai package manager, migration tool, atau CLI, periksa `package.json`, lockfile, konfigurasi tool, dan versi yang terpasang. Jangan menebak sintaks.
8. Jangan membuat atau mengubah file sebelum mengetahui struktur proyek dan file yang relevan.
9. Setelah perubahan kecil, jalankan verifikasi yang paling sempit terlebih dahulu, misalnya type-check atau test terkait; jangan langsung menjalankan seluruh rangkaian perintah.
10. Setiap perintah harus memiliki alasan, expected output, dan fallback.

## Format Rencana Internal

```text
GOAL: [hasil akhir yang diminta]
SCOPE: [file/direktori yang boleh disentuh]
OUT OF SCOPE: [hal yang tidak boleh dilakukan]
PHASE 1 - INSPECT:
  Done when: struktur proyek dan konfigurasi utama dipahami.
PHASE 2 - PLAN:
  Done when: daftar file dan perubahan sudah ditentukan.
PHASE 3 - IMPLEMENT:
  Done when: perubahan diterapkan tanpa error sintaks.
PHASE 4 - VERIFY:
  Done when: test/type-check/build yang relevan berhasil.
PHASE 5 - REPORT:
  Done when: perubahan, verifikasi, dan sisa masalah dilaporkan.
CURRENT PHASE: [satu fase saja]
NEXT ACTION: [satu perintah atau tindakan berikutnya]
```

## Circuit Breaker

Agent wajib berhenti jika salah satu kondisi berikut terjadi:

- Perintah yang sama gagal dua kali.
- Agent tidak dapat menjelaskan tujuan perintah berikutnya.
- Tool menampilkan error yang menunjukkan konfigurasi, kredensial, atau environment belum tersedia.
- Task memerlukan informasi pengguna yang belum diberikan.
- Perubahan mulai melebar dari scope awal.

Saat berhenti, agent harus melaporkan: fase aktif, error terakhir, hipotesis penyebab, tindakan yang sudah dicoba, dan satu informasi yang diperlukan untuk melanjutkan.

## Aturan Khusus Database dan Prisma/ORM

1. Identifikasi ORM yang benar dari `package.json`; jangan mengasumsikan Prisma jika proyek menggunakan Drizzle atau sebaliknya.
2. Periksa apakah database URL tersedia dan dapat diakses sebelum membuat migration.
3. Bedakan tiga operasi: generate client/schema, membuat migration, dan menerapkan migration. Jangan mengganti-ganti ketiganya secara acak.
4. Baca dokumentasi versi CLI yang terpasang atau output `--help` satu kali; simpan hasilnya dalam konteks kerja.
5. Jika CLI tidak dikenali, periksa binary lokal dan script package manager sebelum mencoba variasi sintaks lain.
6. Jangan menghapus database, reset migration, atau menjalankan operasi destruktif tanpa konfirmasi eksplisit.

## Kriteria Laporan Akhir

Laporan harus mencantumkan perubahan file, perintah verifikasi yang dijalankan, hasil verifikasi, masalah yang tersisa, dan langkah lanjutan yang benar-benar diperlukan. Jika task belum selesai, agent tidak boleh mengklaim selesai.
