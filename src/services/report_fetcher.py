import os
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

class BrudamRobot:
    def __init__(self, download_path="data/raw", only_reports=None, start_date_override=None):
        """
        only_reports: lista de report_ids a buscar (ex.: ["147"]). None = todos.
        start_date_override: dict {report_id: "DD/MM/YYYY"} pra sobrepor a data inicial
            hardcoded de um relatório. Útil em backfills.
        """
        self.url = "https://acertaexpress.brudam.com.br"
        self.download_path = download_path
        os.makedirs(download_path, exist_ok=True)
        os.makedirs("debug", exist_ok=True)
        self.viewport = {"width": 1600, "height": 1000}
        self.only_reports = only_reports
        self.start_date_override = start_date_override or {}

    def _log_status(self, message):
        """Writes status to a file for the UI to read."""
        try:
            with open("debug/robot_status.txt", "w", encoding="utf-8") as f:
                f.write(message)
            print(f"Status: {message}")
        except Exception as e:
            print(f"Failed to log status: {e}")

    def fetch_all_reports(self, username, password):
        # Store credentials for potential re-authentication
        self.username = username
        self.password = password
        
        reports_to_fetch = [
            {"id": "106", "name": "emissoes"},
            {"id": "138", "name": "coletas"},
            {"id": "147", "name": "custos_operacao"},  # moved up: Chrome tends to crash on later reports
            {"id": "027", "name": "cotacoes"},
            {"id": "399", "name": "remessas"},
            {"id": "129", "name": "awbs"},
            {"id": "295", "name": "canhotos"},
            {"id": "314", "name": "pereciveis"},
            # 106f = mesmo 106 mas SEM o filtro SEM RECEBEDOR.
            # Usado para fat_dia (faturamento do dia) — inclui notas já entregues hoje.
            # LAST: gera export gigante (~9 meses) que pode crashar Chrome.
            # Se crashar, os 8 relatórios acima já foram salvos.
            {"id": "106f", "name": "emissoes_dia"},
        ]

        # Permite escopar a execução a um subconjunto (backfill, debug, etc.)
        if self.only_reports:
            reports_to_fetch = [r for r in reports_to_fetch if r["id"] in self.only_reports]
            if not reports_to_fetch:
                self._log_status(f"Nenhum relatório válido em only_reports={self.only_reports}.")
                return

        self._log_status("Inicializando Robô...")
        
        import shutil
        _chromium_path = (
            os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
            or shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium-browser")
            or shutil.which("chromium")
            or None
        )
        _is_root = os.getuid() == 0
        # Se tiver DISPLAY (Xvfb ou real), roda headed — compatível com system Chromium
        # para download interception. Se não tiver, usa headless nativo (Mac/CI c/ bundled).
        _has_display = bool(os.environ.get("DISPLAY"))
        _headless = not _has_display
        _launch_args = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu", "--disable-dev-shm-usage"] if _is_root else []
        _launch_kwargs: dict = {"args": _launch_args} if _launch_args else {}
        if _chromium_path:
            _launch_kwargs["executable_path"] = _chromium_path
        with sync_playwright() as p:

            def _new_browser_session():
                """Cria browser + context + page e faz login no Brudam."""
                br = p.chromium.launch(headless=_headless, **_launch_kwargs)
                ctx = br.new_context(accept_downloads=True, viewport=self.viewport)
                ctx.set_default_timeout(60000)
                ctx.set_default_navigation_timeout(60000)
                pg = ctx.new_page()

                self._log_status("Acessando Brudam...")
                print(f"Navigating to {self.url}...")
                pg.goto(self.url, timeout=60000)

                self._log_status("Realizando Login...")
                print("Logging in...")
                pg.fill("#user", username)
                pg.fill("#password", password)
                pg.click("#acessar")
                pg.wait_for_load_state("networkidle", timeout=60000)
                time.sleep(1)

                print("Fechando modals após login...")
                self._close_modals(pg)

                print("Aguardando barra de navegação (#codigo_opcao)...")
                try:
                    pg.wait_for_selector("#codigo_opcao", timeout=30000)
                    print("Barra pronta.")
                except Exception:
                    print("Aviso: #codigo_opcao não apareceu em 30s — continuando mesmo assim.")

                print("Modals fechados, iniciando fetch...")
                return br, pg

            browser = None
            page = None
            try:
                browser, page = _new_browser_session()

                # --- FETCH LOOP (resilient: recreates browser on crash) ---
                total = len(reports_to_fetch)
                for i, report in enumerate(reports_to_fetch):
                    msg = f"Baixando {report['id']} - {report['name'].capitalize()} ({i+1}/{total})..."
                    self._log_status(msg)
                    try:
                        self._fetch_single_report(page, report["id"], report["name"])
                    except Exception as e:
                        err_str = str(e)
                        if "Target page, context or browser has been closed" in err_str or \
                           "Target closed" in err_str or \
                           "Browser has been closed" in err_str:
                            print(f"  ⚠ Browser crashed on {report['id']}: {err_str[:80]}")
                            print(f"  ↻ Recreating browser session...")
                            try: browser.close()
                            except: pass
                            try:
                                browser, page = _new_browser_session()
                                print(f"  ✓ Browser session restored. Continuing with next report.")
                            except Exception as re_err:
                                print(f"  ✗ Could not restore browser: {re_err}")
                                self._log_status(f"Erro Fatal: Browser irrecuperável após crash em {report['id']}")
                                return
                        else:
                            print(f"  Error on {report['id']}: {e}")

                self._log_status("Concluído! Todos os relatórios baixados.")
                print("All reports processed.")

            except Exception as e:
                err_msg = f"Erro Fatal: {e}"
                print(err_msg)
                self._log_status(err_msg)
                try:
                    if page: page.screenshot(path="debug/global_error.png", timeout=5000)
                except:
                    print("Could not take error screenshot.")
            finally:
                try:
                    if browser: browser.close()
                except: pass

    def _wait_for_overlay(self, page):
        """Waits for loading overlays to disappear."""
        try:
            overlay = page.locator("#divOverlay")
            if overlay.is_visible(timeout=1000):
                print("  Waiting for overlay to disappear...")
                overlay.wait_for(state="hidden", timeout=30000)
                print("  Overlay hidden.")
        except:
            pass

    def _close_modals(self, page):
        """Agressivamente fecha qualquer modal/popup que apareça na página"""
        try:
            time.sleep(0.5)

            # Tentar múltiplas vezes fechar diferentes tipos de modais
            for attempt in range(2):
                print(f"Tentativa {attempt + 1} de fechar modais...")
                
                # Seletores para botões de fechar
                close_selectors = [
                    "button:has-text('Fechar')",
                    "button:has-text('fechar')",
                    "button:has-text('Close')",
                    "button[class*='close']",
                    "button[aria-label*='close' i]",
                    ".close-button",
                    "[class*='modal'] button:last-child",
                    "button:has-text('OK')",
                    "button:has-text('OK, entendi')",
                ]
                
                modal_found = False
                for selector in close_selectors:
                    try:
                        btns = page.locator(selector).all()
                        for btn in btns:
                            if btn.is_visible(timeout=1000):
                                print(f"  Fechando: {selector}")
                                btn.click(force=True)
                                modal_found = True
                                time.sleep(0.3)
                    except:
                        pass
                
                # Tentar apertar ESC também
                try:
                    page.press("body", "Escape")
                    print("  Pressionado ESC")
                    modal_found = True
                except:
                    pass
                
                if not modal_found:
                    print("  Nenhum modal encontrado")
                    break

                time.sleep(0.3)
                
        except Exception as e:
            print(f"Erro ao fechar modals: {e}")

    def _fill_date_inputs(self, page, start_date: str, end_date: str):
        """Preenche campos de data com Playwright fill() para disparar eventos do browser."""
        filled_start = False
        for sel in ["input.brd-data:first-of-type", "#data_1", "input[name='data_1']", "input.brd-data"]:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=2000):
                    loc.fill(start_date)
                    loc.press("Tab")
                    filled_start = True
                    print(f"  Início preenchido via '{sel}': {start_date}")
                    break
            except: pass

        filled_end = False
        for sel in ["input.brd-data:last-of-type", "#data_2", "input[name='data_2']"]:
            try:
                loc = page.locator(sel).last
                if loc.is_visible(timeout=2000):
                    loc.fill(end_date)
                    loc.press("Tab")
                    filled_end = True
                    print(f"  Fim preenchido via '{sel}': {end_date}")
                    break
            except: pass

        if not filled_start or not filled_end:
            try:
                inputs = page.locator("input.brd-data").all()
                if len(inputs) >= 2:
                    inputs[0].fill(start_date); inputs[0].press("Tab")
                    inputs[1].fill(end_date);   inputs[1].press("Tab")
                    print(f"  Datas via fallback brd-data: {start_date} → {end_date}")
            except Exception as e:
                print(f"  Aviso: fill() falhou: {e}")

        page.evaluate("""() => {
            document.querySelectorAll('input.brd-data, #data_1, #data_2').forEach(el => {
                ['input','change','blur'].forEach(evt =>
                    el.dispatchEvent(new Event(evt, { bubbles: true }))
                );
            });
        }""")

    def _get_export_selectors_for_report(self, report_id):
        """Returns prioritized list of selectors for export buttons."""
        # Report-specific selectors (confirmed via page inspection)
        specific = {
            "106": [
                "button.btn-excel:not(:has-text('Embarque'))",
            ],
            "106f": [
                "button.btn-excel:not(:has-text('Embarque'))",
            ],
            "138": [
                "img[src*='bt_excel_fat']",
                "img[title*='Excel' i]",
            ],
            "027": [
                "img[src*='bt_excel_fat']",
                "img[title*='Excel' i]",
            ],
            "399": [
                "input[id='excel lista']",
                "input[name='excel lista']",
                "input[id='excel lista2']",
            ],
            "129": [
                "input[id='excel']",
                "input[name='excel lista']",
            ],
            "295": [
                "button#GerarExcel",
                "button.btn-excel:has-text('Excel')",
            ],
        }
        generic = [
            "button.btn-excel",
            "img[src*='bt_excel']",
            "img[title*='Excel' i]",
            "a:has-text('Exportar Excel')",
            "button:has-text('Excel')",
        ]
        return specific.get(report_id, []) + generic


    def _fetch_single_report(self, page, report_id, report_name):
        print(f"--- Fetching Report {report_id} ({report_name}) ---")
        try:
            # 1. Navigate via Shortcut
            shortcut_input = page.locator("#codigo_opcao")
            
            # Check if we're still logged in (shortcut input should be visible)
            if not shortcut_input.is_visible(timeout=10000):
                print("⚠️ Session expired ou página ainda carregando. Navegando para início...")
                # Go directly to inicio.php to avoid root→inicio redirect conflict
                page.goto(f"{self.url}/inicio.php", timeout=60000)
                page.wait_for_load_state("networkidle", timeout=30000)
                time.sleep(0.5)

                shortcut_input = page.locator("#codigo_opcao")
                if not shortcut_input.is_visible(timeout=10000):
                    # Session truly expired — re-login
                    print("Sessão expirada. Re-autenticando...")
                    page.goto(self.url, timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    page.fill("#user", self.username)
                    page.fill("#password", self.password)
                    page.click("#acessar")
                    page.wait_for_load_state("networkidle", timeout=60000)
                    time.sleep(0.5)
                    try:
                        modal_close = page.locator("button:has-text('Fechar')").first
                        if modal_close.is_visible(timeout=2000):
                            modal_close.click()
                            time.sleep(0.3)
                    except: pass

                shortcut_input = page.locator("#codigo_opcao")
                if not shortcut_input.is_visible(timeout=10000):
                    print(f"ERROR: Could not re-authenticate for report {report_id}")
                    return
            
            # 106f é variante interna do report 106 (sem SEM RECEBEDOR) — no Brudam o atalho é 106.
            shortcut_code = "106" if report_id == "106f" else report_id
            shortcut_input.fill(shortcut_code)
            shortcut_input.press("Enter")
            
            # Wait for navigation
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
            except:
                page.wait_for_timeout(2000)
            
            # Check if we got redirected to login (invalid report ID)
            if "login" in page.url.lower() or page.locator("input[name='usuario']").is_visible(timeout=2000):
                print(f"ERROR: Report {report_id} not found or access denied (redirected to login)")
                try:
                    page.screenshot(path=f"debug/fail_{report_id}.png", timeout=5000)
                except: pass
                return
            
            # 2. Fill Date Filters
            # SPECIAL CASE: Report 129 uses 90-day window + RETIRADO = NÃO
            if report_id == "129":
                from datetime import timedelta
                start_date = (datetime.now() - timedelta(days=7)).strftime("%d/%m/%Y")
                end_date = datetime.now().strftime("%d/%m/%Y")
                print(f"Applying last 7 days for {report_id}: {start_date} → {end_date}")
                # Relatório 129 usa #data_inicial / #data_final (diferente dos demais)
                try:
                    page.fill("#data_inicial", start_date)
                    page.fill("#data_final", end_date)
                    page.evaluate(f"""() => {{
                        ['data_inicial','data_final'].forEach(id => {{
                            const el = document.getElementById(id);
                            if (el) ['input','change','blur'].forEach(e => el.dispatchEvent(new Event(e, {{bubbles:true}})));
                        }});
                    }}""")
                    print(f"  [129] Datas preenchidas via #data_inicial/#data_final: {start_date} → {end_date}")
                except Exception as e:
                    print(f"  [129] Aviso ao preencher datas: {e}")

                # Apply RETIRADO = NÃO filter
                try:
                    retirado_select = page.locator("select").filter(has_text="RETIRADO").first
                    if retirado_select.is_visible(timeout=5000):
                        options = retirado_select.locator("option").all()
                        for opt in options:
                            txt = opt.inner_text().strip().upper()
                            if txt in ("NÃO", "NAO", "N"):
                                val = opt.get_attribute("value")
                                retirado_select.select_option(val)
                                print(f"  Applied RETIRADO = NÃO (value={val}) for report 129.")
                                break
                except Exception as e:
                    print(f"  Warning: RETIRADO filter not applied: {e}")
                page.wait_for_load_state("networkidle", timeout=45000)
                time.sleep(2)
                print(f"Report 129: Report should be ready, looking for export button...")
            else:
                # Standard date filter logic for other reports
                from datetime import timedelta
                end_date = datetime.now().strftime("%d/%m/%Y")
                if report_id == "399":
                    print(f"Skipping date filters for {report_id} (system default).")
                elif report_id == "295":
                    start_date = (datetime.now() - timedelta(days=30)).strftime("%d/%m/%Y")
                    print(f"Applying last 30 days for {report_id}: {start_date} → {end_date}")
                    self._fill_date_inputs(page, start_date, end_date)
                elif report_id == "314":
                    start_date = (datetime.now() - timedelta(days=30)).strftime("%d/%m/%Y")
                    print(f"Applying last 30 days for {report_id}: {start_date} → {end_date}")
                    self._fill_date_inputs(page, start_date, end_date)
                elif report_id == "106":
                    start_date = "01/01/2026"
                    print(f"Applying fixed start date for {report_id}: {start_date} → {end_date}")
                    self._fill_date_inputs(page, start_date, end_date)
                elif report_id == "106f":
                    start_date = (datetime.now() - timedelta(days=60)).strftime("%d/%m/%Y")
                    print(f"Applying last 60 days for {report_id}: {start_date} → {end_date}")
                    self._fill_date_inputs(page, start_date, end_date)
                elif report_id == "147":
                    # Relatório de custo por operação — Brudam limita a 30 dias desde Jul/2026.
                    # Aceita override via self.start_date_override["147"] (usado em backfills).
                    start_date = self.start_date_override.get("147", (datetime.now() - timedelta(days=30)).strftime("%d/%m/%Y"))
                    print(f"Applying start date for {report_id}: {start_date} → {end_date}")
                    self._fill_date_inputs(page, start_date, end_date)
                elif report_id == "027":
                    start_date = "01/01/2026"
                    print(f"Applying date 2026 for {report_id} via JS...")
                    page.evaluate(f"""() => {{
                        const d1 = document.getElementById('data_1');
                        const d2 = document.getElementById('data_2');
                        if(d1) d1.value = '{start_date}';
                        if(d2) d2.value = '{end_date}';
                    }}""")
                else:
                    start_date = (datetime.now() - timedelta(days=2)).strftime("%d/%m/%Y")
                    print(f"Applying recent date filter for {report_id} via JS...")
                    page.evaluate(f"""() => {{ 
                        const inputs = document.querySelectorAll('input.brd-data');
                        if(inputs.length >= 2) {{
                            inputs[0].value = '{start_date}';
                            inputs[1].value = '{end_date}';
                        }} else {{
                            const d1 = document.getElementById('data_1');
                            const d2 = document.getElementById('data_2');
                            if(d1) d1.value = '{start_date}';
                            if(d2) d2.value = '{end_date}';
                        }}
                    }}""")
            
            # Scroll to make filters visible and trigger any JS events linked to value changes
            try:
                page.evaluate("window.scrollTo(0, 0)")
                page.evaluate("document.querySelectorAll('input').forEach(i => i.dispatchEvent(new Event('change', {bubbles: true})))")
                time.sleep(0.3)
            except: pass
            
            # --- STATUS FILTER (SEM RECEBEDOR) ---
            # 106f deliberadamente NÃO aplica esse filtro: precisamos do dataset
            # completo (incluindo notas já entregues) pra cálculo de faturamento do dia.
            if report_id in ["106", "027", "399", "314"]:
                print(f"Checking for 'SEM RECEBEDOR' filter for report {report_id}...")
                try:
                    applied = False

                    # Report 106: select has name="select" — find by option text
                    if report_id == "106":
                        sem_recebedor_select = page.locator("select").filter(has_text="SEM RECEBEDOR").first
                        if sem_recebedor_select.is_visible(timeout=5000):
                            sem_recebedor_select.select_option("2")
                            time.sleep(0.3)
                            sem_recebedor_select.press("Tab")
                            applied = True
                            print(f"  Applied SEM RECEBEDOR via filter(has_text) for report 106.")

                    # Reports 027/399: original approach via #situacao
                    if not applied:
                        status_select = page.locator("select[name='situacao'], #situacao")
                        if status_select.is_visible(timeout=5000):
                            options = status_select.locator("option").all()
                            target_val = None
                            for opt in options:
                                text = opt.inner_text().upper()
                                if "SEM RECEBEDOR" in text or "SEM RECEB" in text:
                                    target_val = opt.get_attribute("value")
                                    print(f"  Found target option: '{text}' with value '{target_val}'")
                                    break
                            if target_val:
                                print(f"  Selecting '{target_val}'...")
                                status_select.select_option(target_val)
                                time.sleep(0.3)
                                status_select.press("Tab")
                                applied = True

                    if not applied:
                        print(f"  Warning: SEM RECEBEDOR filter not applied for {report_id}.")
                except Exception as e:
                    print(f"Warning: Failed to apply status filter: {e}")

            # 2.5 Click Pesquisar (Refresh Data)
            # For Report 399, clicking search is CRITICAL to see data
            page.wait_for_load_state("networkidle", timeout=30000)
            search_btn = page.locator("#PESQUISAR")
            if not search_btn.is_visible(timeout=3000):
                search_btn = page.locator("input[value='PESQUISAR']")
            if not search_btn.is_visible(timeout=3000):
                search_btn = page.locator("button:has-text('Pesquisar')")
            if not search_btn.is_visible(timeout=3000):
                search_btn = page.locator("input[value='Pesquisar']")

            if search_btn.is_visible(timeout=10000):
                 print(f"Clicking Search for report {report_id}...")
                 try:
                     self._wait_for_overlay(page)
                     search_btn.click()
                     # Explicitly wait for results table or network idle
                     page.wait_for_load_state("networkidle", timeout=60000)
                     time.sleep(2)
                     self._wait_for_overlay(page)
                     # Report 106 exibe "Montando relatório..." enquanto processa — esperar sumir
                     # 147 (custo por operação) também é pesado — aplica a mesma espera.
                     if report_id in ("106", "106f", "147"):
                         print(f"  Aguardando 'Montando relatório...' desaparecer (report {report_id})...")
                         try:
                             montando = page.locator("text=Montando relatório")
                             # Wait up to 15s for the banner to appear, then wait for it to hide
                             try:
                                 montando.wait_for(state="visible", timeout=15000)
                                 print("  Banner detectado, aguardando processamento...")
                             except Exception:
                                 pass  # Banner may have appeared and gone already
                             montando.wait_for(state="hidden", timeout=300000)
                             print("  Relatório montado.")
                         except Exception as e:
                             print(f"  Aviso: {e}")
                         time.sleep(1)
                     print("Search complete.")
                 except Exception as e:
                     print(f"Warning: Search click had issues: {e}")
            else:
                print(f"Warning: Search button not found for {report_id}")

            # 3. Export via JavaScript click (bypasses visibility checks)
            print(f"Triggering export for {report_id}...")

            # JS snippets confirmed by page inspection
            js_clicks = {
                "106": "Array.from(document.querySelectorAll('button.btn-excel')).find(b => !b.textContent.includes('Embarque'))?.click()",
                "106f": "Array.from(document.querySelectorAll('button.btn-excel')).find(b => !b.textContent.includes('Embarque'))?.click()",
                "138": "document.querySelector('img[src*=\"bt_excel_fat\"]')?.click()",
                "027": "document.querySelector('img[src*=\"bt_excel_fat\"]')?.click()",
                "314": "(document.querySelector('[id=\"excel lista\"]') || document.querySelector('[name=\"excel lista\"]') || document.querySelector('img[src*=\"bt_excel_fat\"]'))?.click()",
                "399": "(document.querySelector('[id=\"excel lista\"]') || document.querySelector('[name=\"excel lista\"]'))?.click()",
                "129": "document.querySelector('#excel')?.click()",
                "295": "document.querySelector('#GerarExcel')?.click()",
                # 147: seletor ainda não confirmado no DOM real. Tenta os padrões usados pelos outros
                # relatórios em ordem; se nenhum casar, o download timeout vai apontar isso no log.
                "147": (
                    "("
                    "document.querySelector('[id=\"excel lista\"]')"
                    " || document.querySelector('[name=\"excel lista\"]')"
                    " || document.querySelector('img[src*=\"bt_excel_fat\"]')"
                    " || document.querySelector('#GerarExcel')"
                    " || document.querySelector('#excel')"
                    " || Array.from(document.querySelectorAll('button.btn-excel')).find(b => !b.textContent.includes('Embarque'))"
                    " || document.querySelector('img[src*=\"excel\"]')"
                    ")?.click()"
                ),
            }

            download_timeout = 300000 if report_id in ("106", "106f", "129", "147") else 60000
            download = None

            try:
                js = js_clicks.get(report_id)
                if js:
                    print(f"  JS click: {js[:60]}...")
                    with page.expect_download(timeout=download_timeout) as download_info:
                        page.evaluate(js)
                        # Check for modal (e.g. report 138 shows XLS/CSV choice)
                        time.sleep(1)
                        for modal_sel in ["button:has-text('Formato XLS')", "button:has-text('XLS')", "a:has-text('Formato XLS')"]:
                            try:
                                mb = page.locator(modal_sel).first
                                if mb.is_visible(timeout=1500):
                                    print(f"  Modal: clicking {modal_sel}")
                                    mb.click()
                                    break
                            except: pass
                    download = download_info.value
                    print(f"  [OK] Download captured!")
                else:
                    # Fallback: CSS selector
                    selectors = self._get_export_selectors_for_report(report_id)
                    btn = None
                    for selector in selectors:
                        try:
                            elem = page.locator(selector).first
                            if elem.count() > 0:
                                try: elem.scroll_into_view_if_needed(timeout=3000)
                                except: pass
                            if elem.is_visible(timeout=3000):
                                btn = elem
                                break
                        except: continue
                    if btn:
                        with page.expect_download(timeout=download_timeout) as download_info:
                            btn.click(timeout=5000)
                        download = download_info.value
                        
            except Exception as e:
                print(f"ERROR during export: {e}")
                # Re-raise browser crash errors so the fetch loop can recover
                err_str = str(e)
                if "Target" in err_str and ("closed" in err_str or "Closed" in err_str):
                    raise
                try:
                    page.screenshot(path=f"debug/fail_{report_id}.png", timeout=5000)
                    with open(f"debug/fail_{report_id}.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except: pass
                return
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{report_id}_{timestamp}.xlsx" 
            save_path = os.path.join(self.download_path, filename)
            
            if download:
                failure = download.failure()
                tmp_path = download.path()
                print(f"  [DEBUG] failure={failure} tmp_path={tmp_path} suggested={download.suggested_filename}")
                download.save_as(save_path)
                saved_size = os.path.getsize(save_path) if os.path.exists(save_path) else -1
                print(f"Saved: {save_path} ({saved_size} bytes)")
            else:
                print(f"ERROR: Download object is None for {report_id}")
                # Save page state for debug
                page.screenshot(path=f"debug/fail_no_download_{report_id}.png")
            
            # Navigate back to home/dashboard to reset state for next report
            page.goto(f"{self.url}/inicio.php", timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)
            self._close_modals(page)

        except Exception as e:
            print(f"Failed to fetch {report_id}: {e}")
            # Re-raise browser crash errors so the fetch loop can recover
            err_str = str(e)
            if "Target" in err_str and ("closed" in err_str or "Closed" in err_str):
                raise
            try: page.screenshot(path=f"debug/fail_{report_id}.png", timeout=5000)
            except: pass
            try:
                page.goto(f"{self.url}/inicio.php", timeout=60000)
                page.wait_for_load_state("networkidle", timeout=30000)
            except: pass

if __name__ == "__main__":
    # Credentials
    user, pwd = None, None
    if os.path.exists("debug/robot_credentials.txt"):
        with open("debug/robot_credentials.txt", "r") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith("USER="): user = line.strip().split("=")[1]
                if line.startswith("PASS="): pwd = line.strip().split("=")[1]
            
    if user and pwd:
        bot = BrudamRobot()
        bot.fetch_all_reports(user, pwd)
    else:
        print("No credentials found.")
