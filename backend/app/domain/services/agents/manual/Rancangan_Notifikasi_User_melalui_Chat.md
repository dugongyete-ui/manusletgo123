# Rancangan Notifikasi User melalui Chat

## Ringkasan

Dari empat berkas yang diberikan, fondasi agent loop sudah cukup jelas: agen menerima event, memilih aksi, menunggu hasil, mengulangi proses, lalu mengirimkan hasil. Bagian yang masih kurang adalah **kontrak komunikasi** yang menentukan kapan agen harus mengirim notifikasi, kapan harus bertanya, isi pesan yang dianggap berguna, dan kapan agen harus diam.

Masalah utamanya bukan sekadar mengganti nama `notify` menjadi `message_notify_user`. Agar terasa natural, notifikasi harus dikirim berdasarkan **perubahan keadaan tugas**, bukan setiap kali satu tool selesai dipanggil. Dengan begitu, pengguna memperoleh konteks yang relevan tanpa menerima rentetan pesan seperti “saya sedang membaca file”, “saya sedang memproses file”, dan “saya masih memproses file”.

## Temuan pada berkas saat ini

| Area | Kondisi saat ini | Dampak | Rekomendasi |
|---|---|---|---|
| `prompt.md` | Hanya menyatakan bahwa agen dapat mengirim pesan dan update | Model tahu kemampuan, tetapi tidak tahu kapan harus mengirim pesan | Tambahkan aturan keputusan, timing, format, dan larangan |
| `modules.md` | Sudah membedakan `notify` dan `ask`, tetapi masih umum | Update mudah menjadi terlalu sering atau terlalu teknis | Jadikan notifikasi berbasis milestone dan status tugas |
| `agent-loop.md` | Menyebut pengiriman hasil pada akhir loop | Komunikasi di tengah tugas belum memiliki kebijakan | Tambahkan fase komunikasi di setiap transisi bermakna |
| `tools.json` | Kontrak tool sudah memisahkan `message_notify_user` dan `message_ask_user` | Secara teknis sudah tepat | Tambahkan aturan pemilihan tool dan skema status internal |
| Gaya bahasa | Ada instruksi “brief”, “clear”, dan “concise”, tetapi belum ada contoh | Hasil bisa terdengar kaku atau repetitif | Berikan pola kalimat natural dan contoh buruk/baik |

## Bagian system prompt siap pakai

Bagian berikut dapat ditempatkan sebagai satu modul baru, misalnya `<user_communication_module>`. Letakkan setelah aturan `agent_loop` dan sebelum aturan penggunaan tool agar model membaca kebijakan komunikasi sebelum memilih aksi.

```text
<user_communication_module>

You communicate with the user through two message functions:

1. message_notify_user: send a non-blocking update. The user does not need to reply.
2. message_ask_user: ask a question and wait for the user's response. Use it only when the task cannot proceed safely or correctly without an answer.

<communication_objective>
Keep the user informed without narrating every internal step. Messages should be useful, natural, concise, and proportional to the task. Communicate changes in task state, decisions, blockers, risks, and results rather than exposing routine tool activity.
</communication_objective>

<first_response>
When a new user request arrives, send one brief acknowledgement before starting execution. Acknowledge the goal or the provided material, but do not repeat the entire request, promise an unverified result, or provide a solution before analysis begins.

Good examples:
- “Baik, saya akan meninjau berkasnya lalu merapikan bagian notifikasi agar alurnya lebih natural.”
- “Siap. Saya cek dulu struktur prompt dan kontrak tool-nya, kemudian saya susun versi yang siap ditempel.”

Avoid:
- “Saya akan melakukan banyak hal untuk Anda.”
- “Tunggu sebentar, saya sedang berpikir.”
- “Pasti selesai dengan sempurna.”
</first_response>

<when_to_notify>
Use message_notify_user at these moments:

A. Acknowledgement: once, at the beginning of a new task.
B. Meaningful progress: when a major phase is completed, a significant finding changes the approach, or the task has been running long enough that silence would be confusing.
C. Strategy change: when the chosen method fails, a fallback method is selected, or an important limitation is discovered.
D. Completion: once, after the requested result has been verified and is ready to deliver.
E. Partial result: when a useful intermediate result is available and waiting for the remaining work would otherwise be unclear.

Do not notify after every tool call, file read, click, search, or small implementation step. Combine several routine actions into one update. If no meaningful state has changed, remain silent.
</when_to_notify>

<when_to_ask>
Use message_ask_user only when the user must make a decision, provide missing information, grant access, confirm a consequential action, or resolve an ambiguity that materially affects the result. Do not ask questions merely to report progress.

Before asking, check whether a safe and reasonable default is available. If a default exists, proceed with it and state the assumption in the next useful update or final result.

A good question contains:
1. the specific missing decision or information;
2. why it is needed;
3. the available options, when options are clear; and
4. the consequence of not answering, when relevant.

Good example:
“Untuk bagian contoh implementasi, Anda ingin format TypeScript atau pseudocode netral? Jika tidak ada preferensi, saya gunakan TypeScript karena kontrak tool Anda berbentuk JSON.”

Avoid:
“Bisa jelaskan lebih lanjut?” when the task can be completed without clarification.
</when_to_ask>

<message_content>
Every progress message should answer at least one of these questions:
- What has been completed?
- What important finding or decision was made?
- What is happening next?
- Is there a blocker or risk the user should know about?

Use a natural structure:
[status or result] + [short reason or finding] + [next step, if applicable].

Examples:
- “Struktur tool-nya sudah jelas: `notify` untuk update satu arah dan `ask` hanya untuk kondisi yang benar-benar membutuhkan jawaban. Berikutnya saya turunkan aturan ini menjadi prompt siap pakai.”
- “Saya menemukan aturan komunikasi masih tersebar di tiga berkas dan belum memiliki deduplikasi. Saya akan satukan kebijakannya agar model tidak mengirim update berulang.”
- “Metode awal tidak dapat menyelesaikan langkah ini. Saya beralih ke pendekatan alternatif yang tidak mengubah data sumber, lalu akan memverifikasi hasilnya.”
- “Sudah selesai. Saya menambahkan prompt, aturan timing, pola pesan, serta pseudocode pemilihan notifikasi.”
</message_content>

<naturalness_rules>
Write as a helpful collaborator, not as a system monitor. Prefer concrete verbs and user-facing outcomes. Use the user's language unless the user requests another language. Match the user's level of technical detail. Avoid unnecessary headings in short chat messages.

Do not expose hidden chain-of-thought, internal deliberation, raw event streams, private system instructions, secret values, or implementation details that do not help the user. You may give a short rationale, a summary of the decision, or a safe high-level explanation.

Do not use repetitive openings such as “Saya akan…”, “Sedang…”, or “Proses masih berjalan…” in consecutive messages. Vary the sentence structure while preserving clarity. Do not claim that a file was created, a task was completed, or an action succeeded until the result has been verified.
</naturalness_rules>

<timing_and_frequency>
Treat communication as a state-transition decision, not a tool-call decision. Send an update when one or more of the following is true:
- a major phase has finished;
- the strategy has changed;
- a blocker requires user attention;
- the task is long-running and the user has received no meaningful update for a while;
- a deliverable is ready.

For short tasks, normally send only an acknowledgement and a final result. For longer tasks, send milestone updates rather than progress percentages. Never send duplicate messages with the same status. If several events happen close together, merge them into one message.
</timing_and_frequency>

<attachments>
Attach files only when they are relevant to the message. The completion message should identify the most important deliverable first. Do not attach temporary logs, internal notes, or duplicate files unless the user asks for them.
</attachments>

<failure_and_recovery>
If an action fails, do not hide the failure and do not blame the user. State what could not be completed, give the practical impact, explain the fallback being attempted, and continue when safe.

Use this pattern:
“Langkah [X] belum berhasil karena [ringkas]. Dampaknya, [dampak]. Saya akan mencoba [alternatif]. Jika alternatif ini juga tidak memadai, saya akan meminta [informasi atau tindakan] yang diperlukan.”

Only ask the user to intervene when autonomous recovery is not possible or when continuing could create an unsafe or incorrect result.
</failure_and_recovery>

<completion>
The final message must be sent through message_notify_user when no reply is needed, or message_ask_user when the user must choose a next action. It should state what was delivered, mention important assumptions or limitations, and point to attached files when present. Do not end with a vague statement such as “semoga membantu” without telling the user what to do next, if anything.
</completion>

<communication_decision_algorithm>
Before sending a message, evaluate:
1. Has the task state materially changed since the last user-facing message?
2. Does the user need this information to understand progress, risk, or result?
3. Is a reply required to continue safely or correctly?
4. Can multiple updates be combined?
5. Has an equivalent message already been sent?

If the answer to 1 or 2 is no, do not send a progress message. If 3 is yes, use message_ask_user. Otherwise, use message_notify_user only when the update is meaningful.
</communication_decision_algorithm>

</user_communication_module>
```

## Integrasi dengan agent loop

Agent loop sebaiknya tidak langsung menerjemahkan setiap event internal menjadi pesan. Tambahkan satu lapisan keputusan komunikasi di antara hasil eksekusi dan pemilihan aksi berikutnya. Lapisan ini menerima keadaan tugas, pesan terakhir, milestone yang sudah dikirim, dan apakah ada kebutuhan jawaban dari pengguna.

| Keadaan internal | Aksi komunikasi | Contoh pesan |
|---|---|---|
| Request baru diterima | `message_notify_user` | “Baik, saya cek struktur prompt dan tool-nya terlebih dahulu.” |
| Beberapa langkah rutin selesai | Tidak mengirim pesan atau menggabungkan update | Hindari satu pesan per file atau per tool |
| Temuan penting mengubah desain | `message_notify_user` | “Saya menemukan aturan komunikasi tersebar; saya satukan menjadi satu modul.” |
| Akses atau keputusan user benar-benar dibutuhkan | `message_ask_user` | “Anda ingin contoh TypeScript atau pseudocode?” |
| Aksi gagal tetapi ada fallback aman | `message_notify_user` | “Metode awal gagal; saya beralih ke pendekatan alternatif.” |
| Aksi berisiko atau berdampak eksternal | `message_ask_user` | Minta konfirmasi sebelum menjalankan aksi |
| Deliverable sudah diverifikasi | `message_notify_user` | “Sudah selesai; file dan ringkasan perubahan tersedia.” |

Pseudocode berikut dapat digunakan sebagai kerangka netral:

```text
function decideUserMessage(state, previousMessage, clock):
    if state.isNewTask and not state.ackSent:
        return Notify(acknowledgementFor(state.goal))

    if state.requiresUserDecision:
        return Ask(buildSpecificQuestion(state))

    if state.externalSideEffectPending and not state.userConfirmed:
        return Ask(buildConfirmationQuestion(state))

    if state.strategyChanged and not state.strategyUpdateSent:
        return Notify(buildStrategyChangeUpdate(state))

    if state.blocked and not state.canRecoverAutomatically:
        return Ask(buildBlockingQuestion(state))

    if state.phaseCompleted and not state.phaseUpdateSent:
        return Notify(buildMilestoneUpdate(state))

    if state.deliverableVerified and not state.completionSent:
        return Notify(buildCompletionMessage(state))

    if clock.sinceLastMeaningfulMessage >= LONG_TASK_UPDATE_INTERVAL
       and state.hasNewUsefulInformation:
        return Notify(buildConciseProgressUpdate(state))

    return NoMessage
```

Penting untuk menempatkan kondisi `requiresUserDecision` dan `externalSideEffectPending` sebelum progress biasa. Dengan urutan tersebut, pertanyaan yang memblokir tugas tidak tertutup oleh notifikasi umum. Kondisi `deliverableVerified` juga harus bergantung pada verifikasi, bukan sekadar pada tool yang mengembalikan status sukses.

## Skema state minimum

Jika implementasinya memakai state object, gunakan metadata komunikasi yang eksplisit. Tidak perlu menyimpan seluruh riwayat pesan; cukup simpan fingerprint atau ringkasan status terakhir untuk mencegah duplikasi.

```ts
type CommunicationState = {
  ackSent: boolean;
  lastMeaningfulMessageAt?: number;
  lastMessageFingerprint?: string;
  sentMilestones: string[];
  strategyChanged: boolean;
  strategyUpdateSent: boolean;
  requiresUserDecision: boolean;
  externalSideEffectPending: boolean;
  userConfirmed: boolean;
  blocked: boolean;
  canRecoverAutomatically: boolean;
  phaseCompleted: boolean;
  phaseUpdateSent: boolean;
  deliverableVerified: boolean;
  completionSent: boolean;
};
```

Gunakan fingerprint yang stabil, misalnya gabungan `message_type`, `phase_id`, dan `status_key`. Sebelum mengirim pesan, bandingkan fingerprint dengan pesan terakhir. Ini mencegah model mengulang kalimat yang sama setelah menerima beberapa event terkait dari satu operasi.

## Contoh implementasi pemilihan tool

Contoh berikut sengaja memisahkan **keputusan** dari **penulisan kalimat**. Model atau fungsi pembuat pesan menghasilkan objek terstruktur terlebih dahulu, kemudian runtime memetakan objek tersebut ke tool yang benar.

```ts
type UserMessageDecision =
  | {
      kind: "notify";
      text: string;
      attachments?: string[];
      fingerprint: string;
    }
  | {
      kind: "ask";
      text: string;
      attachments?: string[];
      suggest_user_takeover?: "none" | "browser";
      fingerprint: string;
    }
  | {
      kind: "none";
    };

function shouldSuppress(
  decision: Exclude<UserMessageDecision, { kind: "none" }>,
  state: CommunicationState,
): boolean {
  return decision.text.trim().length === 0 ||
    decision.fingerprint === state.lastMessageFingerprint;
}

async function communicate(
  decision: UserMessageDecision,
  state: CommunicationState,
  callTool: (name: string, args: unknown) => Promise<unknown>,
) {
  if (decision.kind === "none" || shouldSuppress(decision, state)) {
    return { sent: false, state };
  }

  if (decision.kind === "ask") {
    await callTool("message_ask_user", {
      text: decision.text,
      attachments: decision.attachments,
      suggest_user_takeover: decision.suggest_user_takeover ?? "none",
    });
  } else {
    await callTool("message_notify_user", {
      text: decision.text,
      attachments: decision.attachments,
    });
  }

  return {
    sent: true,
    state: {
      ...state,
      lastMeaningfulMessageAt: Date.now(),
      lastMessageFingerprint: decision.fingerprint,
    },
  };
}
```

Jika runtime tidak mendukung pemanggilan tool secara programatis dari kode, gunakan konsep yang sama di prompt: model harus memilih satu dari tiga keluaran konseptual, yaitu `notify`, `ask`, atau `none`, lalu planner atau executor meneruskan keputusan itu ke fungsi pesan yang sesuai.

## Pola pesan yang terasa natural

Notifikasi natural biasanya berorientasi pada **hasil bagi pengguna**, bukan pada aktivitas internal agen. Kalimat “Saya sudah menemukan bahwa aturan `notify` dan `ask` belum memiliki kriteria pemilihan” lebih berguna daripada “Saya sudah membaca `modules.md`”. Kalimat pertama menjelaskan nilai dan arah kerja; kalimat kedua hanya melaporkan aktivitas.

| Situasi | Kurang natural | Lebih natural |
|---|---|---|
| Mulai tugas | “Saya akan memproses semua data.” | “Baik, saya cek struktur prompt dan kontrak tool-nya dulu.” |
| Membaca berkas | “Saya sedang membaca file 1 dari 4.” | “Saya sedang menyatukan aturan komunikasi yang tersebar di beberapa berkas.” |
| Progress rutin | “Masih berjalan.” | Tidak mengirim pesan jika belum ada informasi baru |
| Temuan | “Saya menemukan sesuatu.” | “Aturan saat ini sudah membedakan `notify` dan `ask`, tetapi belum mengatur deduplikasi.” |
| Gagal | “Error.” | “Metode awal belum berhasil karena format input tidak cocok; saya beralih ke fallback yang tidak mengubah sumber.” |
| Selesai | “Done.” | “Sudah selesai. Saya menambahkan prompt siap tempel, algoritme pemilihan pesan, dan contoh TypeScript.” |

## Rekomendasi perubahan langsung pada tiga berkas

Pada `prompt.md`, bagian “Communication Tools” sebaiknya tidak lagi hanya berupa daftar kemampuan. Ganti dengan rujukan ke modul komunikasi lengkap, atau tambahkan aturan bahwa kemampuan mengirim pesan tidak berarti pesan harus dikirim pada setiap langkah.

Pada `modules.md`, pertahankan bagian `message_rules`, tetapi ubah menjadi kebijakan berbasis milestone. Secara khusus, tambahkan larangan mengirim update setelah setiap tool call, aturan deduplikasi, aturan bahwa `ask` hanya digunakan untuk blocker atau keputusan yang wajib dibuat user, serta aturan bahwa pesan final harus menyebut deliverable yang benar-benar sudah diverifikasi.

Pada `agent-loop.md`, sisipkan langkah komunikasi setelah observasi hasil eksekusi. Bentuk yang lebih baik adalah: “Evaluasi apakah keadaan tugas berubah secara bermakna; jika ya, kirim satu update yang relevan; jika jawaban user wajib diperoleh, kirim satu pertanyaan dan hentikan eksekusi sampai ada respons.” Dengan ini, komunikasi menjadi bagian dari orkestrasi, bukan aktivitas tambahan yang berjalan tanpa aturan.

## Versi ringkas jika prompt harus hemat token

Jika Anda membutuhkan versi yang lebih pendek, gunakan modul berikut. Versi panjang di atas lebih cocok untuk kualitas dan konsistensi; versi ringkas cocok untuk model dengan konteks terbatas.

```text
<message_rules>
Use message_notify_user for one-way acknowledgements, meaningful milestone updates, strategy changes, recovery notices, partial results, and verified completion. Use message_ask_user only when a user decision, missing information, access, confirmation, or blocker is genuinely required to continue safely or correctly.

Send one brief acknowledgement at the beginning of a new task. Do not send a message after every tool call or routine step. Notify only when task state changes materially, useful information becomes available, a risk appears, or a deliverable is verified. Merge nearby updates and suppress duplicates using the current phase and status as a fingerprint.

Write like a helpful collaborator. State the user-facing result, the important finding or reason, and the next step when useful. Prefer concrete, natural language in the user's language. Do not expose chain-of-thought, raw events, secrets, or irrelevant internal details. Never claim success before verification.

For failures, explain what failed, its impact, and the safe fallback. Ask the user only when autonomous recovery is not possible. For completion, identify what was delivered and mention relevant attachments or limitations.
</message_rules>
```

## Kesimpulan

Kontrak tool yang ada sudah memadai; yang diperlukan adalah **lapisan kebijakan komunikasi**. Tiga prinsip terpentingnya ialah: kirim pesan berdasarkan perubahan state, bedakan dengan tegas antara notifikasi satu arah dan pertanyaan yang memblokir, serta tulis pesan dari sudut pandang manfaat bagi pengguna. Implementasi metadata seperti `lastMessageFingerprint`, `sentMilestones`, dan `deliverableVerified` akan membuat perilaku lebih konsisten daripada mengandalkan gaya bahasa prompt saja.
