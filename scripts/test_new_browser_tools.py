"""Live test untuk 4 tool browser baru (parity browser-use cloud):
browser_search_page, browser_find_elements, browser_find_text, browser_close_tab.
Dijalankan langsung terhadap Chrome lokal sandbox (CDP :8222) — tanpa E2B.
"""
import asyncio
import sys

sys.path.insert(0, "/home/z/my-project/backend")

from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser


async def main() -> int:
    b = BrowserUseBrowser(cdp_url="http://localhost:8222", display_size=(1280, 1029))
    results = []

    def check(label, cond, detail=""):
        results.append((label, cond, detail))
        print(f"{'PASS' if cond else 'FAIL'} — {label} {detail}")

    try:
        # 1) Navigate ke halaman test lokal (ringan, deterministik)
        r = await b.navigate("https://example.com")
        check("navigate example.com", r.success, str(r.message)[:80])

        # 2) search_page — cari teks yang ada
        r = await b.search_page("Example Domain")
        found = r.success and r.data.get("total_matches", 0) >= 1
        check("search_page finds 'Example Domain'", found, f"total={r.data.get('total_matches') if r.success else r.message}")

        # 3) search_page — regex
        r2 = await b.search_page(r"Domain\s", is_regex=True)
        check("search_page regex", r2.success and r2.data.get("total_matches", 0) >= 1)

        # 4) search_page — teks yang TIDAK ada
        r3 = await b.search_page("teks-tidak-ada-xyz123")
        check("search_page zero-match graceful", r3.success and r3.data.get("total_matches") == 0, str(r3.message)[:60])

        # 5) find_elements — hitung paragraf
        r4 = await b.find_elements("p")
        ok4 = r4.success and r4.data.get("total", 0) >= 1
        first = (r4.data.get("elements") or [{}])[0] if r4.success else {}
        check("find_elements 'p'", ok4, f"total={r4.data.get('total') if r4.success else r4.message}, tag={first.get('tag')}")

        # 6) find_elements — selector invalid → error jelas
        r5 = await b.find_elements(">>>invalid[[")
        check("find_elements invalid selector handled", (not r5.success) or r5.data.get("error"), str(r5.message)[:60])

        # 7) find_text — scroll ke teks
        r6 = await b.find_text("Example Domain")
        d6 = r6.data or {}
        check("find_text found+scrolled", r6.success and d6.get("found") is True, str(d6.get("tag")))

        # 8) find_text — tidak ada
        r7 = await b.find_text("teks-tidak-ada-xyz123")
        d7 = r7.data or {}
        check("find_text not-found graceful", r7.success and d7.get("found") is False)

        # 9) close_tab — buka tab kedua lalu tutup; guard tab terakhir
        r8 = await b.open_tab("https://www.iana.org/help/example-domains")
        ntabs = r8.data.get("total_tabs", 2) if r8.success else 2
        check("open_tab #2", r8.success, f"total={ntabs}")
        r9 = await b.close_tab(2)
        check("close_tab #2", r9.success, str(r9.message)[:80])
        r10 = await b.close_tab(99)
        check("close_tab index invalid ditolak", not r10.success)
        r11 = await b.close_tab(1)
        check("close_guard tab terakhir ditolak", not r11.success, str(r11.message)[:70])

        # 10) Verifikasi status tab setelah tutup
        r12 = await b.list_tabs()
        check("list_tabs konsisten 1 tab", r12.success and r12.data.get("total_tabs") == 1)

    finally:
        try:
            await b.cleanup()
        except Exception:
            pass

    failed = [r for r in results if not r[1]]
    print(f"\n=== {len(results) - len(failed)}/{len(results)} PASSED ===")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
