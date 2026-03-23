"""
🤖 BOT DE INVERSIÓN COMPLETO (v4.0 - CON CRYPTO)

COMANDOS:
!balance            - P&L del portafolio
!señales            - Señales de venta
!reporte [presupuesto] - Reporte quincenal (90% activos + 10% crypto)
!portafolio         - Ver holdings
!vender [t] [qty]   - Vender shares
!comprar [t] [qty] [precio] - Comprar shares
!discover [n]       - Descubrir nuevos activos
!discover_commit    - Aprobar sugerencias
!discover_status    - Estado de discover
!debug [ticker]     - Debug de un ticker
!debug_total        - Pesos del portafolio
!test_github        - Diagnostico GitHub
!help               - Lista de comandos

CAMBIOS v4.0:
  ✅ 10% del presupuesto va a crypto (Bitso)
  ✅ IA recomienda 2 cryptos según tu perfil de portafolio
  ✅ Universo de cryptos: BTC, ETH, SOL, LINK, ADA, AVAX
  ✅ Datos de crypto vía yfinance (BTC-USD, ETH-USD, etc.)
"""

import os, json, math, traceback
import discord
from discord.ext import commands, tasks
from datetime import datetime, time
import requests
import yfinance as yf
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import time as time_module

# ════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════

BOT_TOKEN         = os.getenv("DISCORD_BOT_TOKEN")
GITHUB_REPO       = os.getenv("GB_REPO")
GITHUB_TOKEN      = os.getenv("GB_TOKEN")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
CHANNEL_ID_STR    = os.getenv("DISCORD_CHANNEL_ID")

CHANNEL_ID = None
if CHANNEL_ID_STR:
    try:
        CHANNEL_ID = int(CHANNEL_ID_STR)
    except ValueError:
        print(f"⚠️ DISCORD_CHANNEL_ID inválido: {CHANNEL_ID_STR}")

OPENAI_MODEL      = "gpt-4o"          # cambia si usas otro modelo
CRYPTO_BUDGET_PCT = 0.10              # 10% del presupuesto para crypto

last_report_day   = None
last_discover_day = None
user_sessions     = {}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

client_openai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ════════════════════════════════════════════════════════════════
# UNIVERSO DE CRYPTOS
# ════════════════════════════════════════════════════════════════

CRYPTO_UNIVERSE = [
    {
        "ticker": "BTC",
        "yahoo": "BTC-USD",
        "name": "Bitcoin",
        "profile_tags": ["store_of_value", "tech_corr", "growth", "defensivo"],
        "description": "Reserva de valor digital, correlación positiva con tech"
    },
    {
        "ticker": "ETH",
        "yahoo": "ETH-USD",
        "name": "Ethereum",
        "profile_tags": ["infraestructura", "yield_staking", "growth", "tech_corr"],
        "description": "Plataforma de contratos inteligentes, yield via staking ~4%"
    },
    {
        "ticker": "SOL",
        "yahoo": "SOL-USD",
        "name": "Solana",
        "profile_tags": ["growth", "infraestructura", "alta_volatilidad"],
        "description": "L1 de alto rendimiento, ecosistema DeFi activo"
    },
    {
        "ticker": "LINK",
        "yahoo": "LINK-USD",
        "name": "Chainlink",
        "profile_tags": ["infraestructura", "datos_ia", "growth"],
        "description": "Oracle on-chain, relacionado a datos/IA (encaja con NVDA exposure)"
    },
    {
        "ticker": "ADA",
        "yahoo": "ADA-USD",
        "name": "Cardano",
        "profile_tags": ["infraestructura", "moderado"],
        "description": "L1 con enfoque académico/seguridad, riesgo relativo bajo"
    },
    {
        "ticker": "AVAX",
        "yahoo": "AVAX-USD",
        "name": "Avalanche",
        "profile_tags": ["infraestructura", "growth", "defi"],
        "description": "L1 con subnets, fuerte en DeFi institucional"
    },
]

# ════════════════════════════════════════════════════════════════
# GITHUB
# ════════════════════════════════════════════════════════════════

def github_get_file(path: str):
    import base64
    if not GITHUB_REPO or not GITHUB_TOKEN:
        print(f"❌ Configuración GitHub faltante")
        return None, None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            content = resp.json()["content"]
            decoded = base64.b64decode(content).decode("utf-8")
            sha = resp.json()["sha"]
            return json.loads(decoded), sha
        return None, None
    except Exception as e:
        print(f"❌ github_get_file error: {e}")
        return None, None


def github_save_file(path: str, data: dict, sha: str, commit_msg: str, branch: str = "main"):
    import base64
    if not GITHUB_REPO or not GITHUB_TOKEN or not sha:
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    try:
        content_encoded = base64.b64encode(
            json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": commit_msg, "content": content_encoded, "sha": sha, "branch": branch}
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"❌ github_save_file error: {e}")
        return False

# ════════════════════════════════════════════════════════════════
# PRECIOS Y DATOS DE MERCADO
# ════════════════════════════════════════════════════════════════

def get_usd_to_mxn(fallback=17.0):
    try:
        for symbol in ("USDMXN=X", "MXN=X"):
            hist = yf.Ticker(symbol).history(period="5d")
            if not hist.empty:
                rate = float(hist["Close"].dropna().iloc[-1])
                if rate < 1:
                    rate = 1 / rate
                if rate > 0:
                    print(f"💱 FX ({symbol}): 1 USD = {rate:.4f} MXN")
                    return rate
        return fallback
    except Exception as e:
        print(f"❌ get_usd_to_mxn error: {e}")
        return fallback


def get_price_with_retry(yahoo_ticker: str, max_retries: int = 3, timeout: int = 10):
    for attempt in range(max_retries):
        try:
            ticker_obj = yf.Ticker(yahoo_ticker)
            price = None
            try:
                if hasattr(ticker_obj, 'fast_info'):
                    price = ticker_obj.fast_info.last_price
                    if price and price > 0:
                        return price
            except:
                pass
            try:
                info = ticker_obj.info
                price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
                if price and price > 0:
                    return price
            except:
                pass
            try:
                hist = ticker_obj.history(period="1d")
                if not hist.empty:
                    close = hist['Close'].dropna()
                    if len(close) > 0:
                        return float(close.iloc[-1])
            except:
                pass
            if attempt < max_retries - 1:
                time_module.sleep((attempt + 1) * 2)
        except Exception as e:
            if attempt < max_retries - 1:
                time_module.sleep(2)
    return None


def validate_price(price, ticker: str) -> bool:
    if price is None or price <= 0 or price > 1_000_000 or price < 0.01:
        return False
    return True


def get_last_close_and_currency(yahoo_ticker: str):
    t = yf.Ticker(yahoo_ticker)
    hist = t.history(period="5d")
    if hist.empty or "Close" not in hist:
        return None, None
    close = hist["Close"].dropna()
    if close.empty:
        return None, None
    price = float(close.iloc[-1])
    if yahoo_ticker.endswith('.MX'):
        currency = "MXN"
    else:
        currency = None
        try:
            currency = t.fast_info.currency
        except:
            pass
        if not currency:
            try:
                currency = t.info.get("currency")
            except:
                currency = "USD"
    return price, currency


def to_mxn(value: float, currency: str, usd_to_mxn: float) -> float:
    if value is None:
        return None
    if currency == "USD":
        return float(value) * float(usd_to_mxn)
    return float(value)


def _get_market_data_sync(universe, max_workers: int = 5, timeout_per_ticker: int = 15):
    print(f"\n📊 Descargando datos de mercado ({len(universe)} tickers)...")
    market_data = {}

    def process_ticker(item):
        ticker   = item["ticker"]
        y_ticker = item["yahoo"]
        try:
            price = get_price_with_retry(y_ticker, max_retries=3, timeout=timeout_per_ticker)
            if not price or price <= 0:
                return ticker, {"price": None, "ret_3m": None}
            ticker_obj = yf.Ticker(y_ticker)
            hist = ticker_obj.history(period="6mo")
            if hist is None or hist.empty:
                return ticker, {"price": price, "ret_3m": None}
            close = hist["Close"].dropna()
            if len(close) < 64:
                return ticker, {"price": price, "ret_3m": None}
            close_3m = close.iloc[-64:]
            ret_3m = float(close_3m.iloc[-1] / close_3m.iloc[0] - 1.0)
            return ticker, {"price": price, "ret_3m": ret_3m}
        except Exception as e:
            return ticker, {"price": None, "ret_3m": None}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(process_ticker, item): item["ticker"] for item in universe}
        for future in future_to_ticker:
            t_name = future_to_ticker[future]
            try:
                ticker, data = future.result(timeout=timeout_per_ticker + 5)
                market_data[ticker] = data
            except FuturesTimeoutError:
                market_data[t_name] = {"price": None, "ret_3m": None}
            except Exception as e:
                market_data[t_name] = {"price": None, "ret_3m": None}

    with_price = sum(1 for d in market_data.values() if d.get("price"))
    print(f"✅ Precios obtenidos: {with_price}/{len(market_data)}")
    return market_data

# ════════════════════════════════════════════════════════════════
# CRYPTO: DATOS Y RECOMENDACIÓN
# ════════════════════════════════════════════════════════════════

def get_crypto_data_sync(usd_to_mxn: float) -> dict:
    """Descarga precios y métricas de las cryptos candidatas."""
    print("\n₿ Descargando datos de crypto...")
    crypto_data = {}

    for crypto in CRYPTO_UNIVERSE:
        ticker = crypto["ticker"]
        yahoo  = crypto["yahoo"]
        try:
            t    = yf.Ticker(yahoo)
            hist = t.history(period="6mo")
            if hist is None or hist.empty:
                continue
            close = hist["Close"].dropna()
            if len(close) == 0:
                continue

            price_usd = float(close.iloc[-1])
            price_mxn = price_usd * usd_to_mxn

            ret_3m = vol_3m = score = None
            window = 63
            if len(close) >= window + 1:
                close_3m  = close.iloc[-(window + 1):]
                ret_3m    = float(close_3m.iloc[-1] / close_3m.iloc[0] - 1.0)
                daily_ret = close_3m.pct_change().dropna()
                vol_3m    = float(daily_ret.std() * math.sqrt(window))
                if vol_3m and vol_3m > 0:
                    score = ret_3m / vol_3m

            crypto_data[ticker] = {
                "price_usd":   price_usd,
                "price_mxn":   price_mxn,
                "ret_3m":      ret_3m,
                "vol_3m":      vol_3m,
                "score":       score,
                "name":        crypto["name"],
                "profile_tags":crypto["profile_tags"],
                "description": crypto["description"],
            }
            r = f"{ret_3m:+.1%}" if ret_3m else "N/A"
            s = f"{score:.2f}"   if score  else "N/A"
            print(f"  ✅ {ticker:6} ${price_usd:>9,.2f} USD | ret3M={r} | score={s}")

        except Exception as e:
            print(f"  ❌ {ticker}: {str(e)[:60]}")

    print(f"  Cryptos obtenidas: {len(crypto_data)}/{len(CRYPTO_UNIVERSE)}")
    return crypto_data


def get_crypto_recommendation_sync(
    crypto_data: dict,
    budget_crypto: float,
    usd_to_mxn: float,
    portfolio: dict,
) -> dict:
    """Recomienda 2 cryptos según perfil del portafolio usando IA."""

    holdings_summary = []
    for broker, acc in portfolio.get("accounts", {}).items():
        for h in acc.get("holdings", []):
            holdings_summary.append(f"{h['ticker']}({h['type']})")

    crypto_lines = []
    for ticker, data in crypto_data.items():
        r = f"{data['ret_3m']:+.1%}" if data.get("ret_3m") is not None else "N/A"
        v = f"{data['vol_3m']:.2f}"  if data.get("vol_3m") is not None else "N/A"
        s = f"{data['score']:.2f}"   if data.get("score")  is not None else "N/A"
        crypto_lines.append(
            f"• {ticker} ({data['name']}): ${data['price_usd']:,.2f} USD | "
            f"ret3M={r} | vol={v} | score={s} | tags={','.join(data['profile_tags'])} | "
            f"{data['description']}"
        )

    prompt = f"""
Eres analista de criptomonedas para portafolios mixtos.

PORTAFOLIO ACTUAL: {', '.join(holdings_summary)}
PERFIL: Tech-pesado (NVDA,GOOG,MSFT,AAPL), dividendos+crecimiento 60/40, largo plazo, moderado, broker Bitso.

CRYPTOS DISPONIBLES:
{chr(10).join(crypto_lines)}

FX: 1 USD = {usd_to_mxn:.2f} MXN
PRESUPUESTO CRYPTO: ${budget_crypto:,.2f} MXN

Recomienda EXACTAMENTE 2 cryptos complementarias al perfil.
Distribuye: 70% a la de menor riesgo relativo, 30% a la de mayor potencial.

RESPONDE SOLO JSON (sin markdown):
{{
  "recommendations": [
    {{"ticker": "BTC", "allocation_pct": 70, "amount_mxn": 0,
      "reason_short": "Store of value - correlación tech bull markets",
      "risk_level": "MEDIO"}},
    {{"ticker": "ETH", "allocation_pct": 30, "amount_mxn": 0,
      "reason_short": "Infraestructura digital - staking yield ~4%",
      "risk_level": "MEDIO-ALTO"}}
  ],
  "strategy_summary": "2 líneas explicando la estrategia crypto para este perfil",
  "warning": "Recordatorio de riesgo específico"
}}"""

    def _build_plan(recs):
        plan = {}
        for rec in recs:
            t = rec["ticker"]
            pct = rec.get("allocation_pct", 50) / 100
            amount = round(budget_crypto * pct, 2)
            rec["amount_mxn"] = amount
            mkt = crypto_data.get(t, {})
            p_usd = mkt.get("price_usd", 0)
            p_mxn = mkt.get("price_mxn", 1)
            plan[t] = {
                "amount_mxn":    amount,
                "amount_usd":    round(amount / usd_to_mxn, 2),
                "qty_crypto":    round(amount / p_mxn, 8) if p_mxn > 0 else 0,
                "price_usd":     p_usd,
                "price_mxn":     p_mxn,
                "allocation_pct":rec.get("allocation_pct", 50),
                "risk_level":    rec.get("risk_level", "MEDIO"),
                "reason":        rec.get("reason_short", ""),
            }
        return plan

    if client_openai:
        try:
            response = client_openai.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "Eres analista de crypto. Respondes SOLO JSON sin markdown."},
                    {"role": "user",   "content": prompt}
                ],
                max_completion_tokens=800,
                temperature=0.3,
            )
            content = response.choices[0].message.content.strip()
            for tag in ["```json", "```"]:
                content = content.replace(tag, "")
            content = content.strip()
            result = json.loads(content)
            recs   = result.get("recommendations", [])
            return {
                "success":          True,
                "recommendations":  recs,
                "plan":             _build_plan(recs),
                "strategy_summary": result.get("strategy_summary", ""),
                "warning":          result.get("warning", ""),
                "total_budget":     budget_crypto,
            }
        except Exception as e:
            print(f"⚠️ IA crypto falló ({e}), usando fallback BTC/ETH")

    # Fallback sin IA
    fallback_recs = [
        {"ticker": "BTC", "allocation_pct": 70, "amount_mxn": 0,
         "reason_short": "Store of value - fallback por defecto", "risk_level": "MEDIO"},
        {"ticker": "ETH", "allocation_pct": 30, "amount_mxn": 0,
         "reason_short": "Infraestructura digital - fallback por defecto", "risk_level": "MEDIO-ALTO"},
    ]
    return {
        "success":          True,
        "recommendations":  fallback_recs,
        "plan":             _build_plan(fallback_recs),
        "strategy_summary": "BTC como reserva de valor, ETH como infraestructura digital (recomendación por defecto).",
        "warning":          "IA no disponible. Revisa manualmente antes de comprar.",
        "total_budget":     budget_crypto,
    }

# ════════════════════════════════════════════════════════════════
# EVALUATE SELLS
# ════════════════════════════════════════════════════════════════

async def evaluate_sells(portfolio: dict):
    universe, _ = github_get_file("data/universe.json")
    if not universe:
        return []

    yahoo_map = {item["ticker"]: item["yahoo"] for item in universe}

    import asyncio
    loop = asyncio.get_event_loop()

    usd_to_mxn  = await loop.run_in_executor(None, get_usd_to_mxn)
    market_data = await loop.run_in_executor(None, _get_market_data_sync, universe, 5, 15)

    STOP_LOSS   = -0.25
    TAKE_PROFIT =  0.80
    REBALANCE   =  0.35

    total_value_mxn = 0.0
    for broker, acc in portfolio.get("accounts", {}).items():
        for h in acc.get("holdings", []):
            ticker       = h["ticker"]
            shares       = float(h["shares"])
            avg_cost     = float(h["avg_cost"])
            yahoo_ticker = yahoo_map.get(ticker, "")
            data         = market_data.get(ticker, {})
            price_raw    = data.get("price")
            if price_raw:
                price_mxn = price_raw if yahoo_ticker.endswith(".MX") else price_raw * usd_to_mxn
            else:
                price_mxn = avg_cost
            total_value_mxn += shares * price_mxn

    sell_signals = []
    for broker, acc in portfolio.get("accounts", {}).items():
        for h in acc.get("holdings", []):
            ticker       = h["ticker"]
            shares       = float(h["shares"])
            avg_cost     = float(h["avg_cost"])
            yahoo_ticker = yahoo_map.get(ticker, "")
            data         = market_data.get(ticker, {})
            price_raw    = data.get("price")
            if not price_raw:
                continue
            price_mxn     = price_raw if yahoo_ticker.endswith(".MX") else price_raw * usd_to_mxn
            current_value = shares * price_mxn
            cost_basis    = shares * avg_cost
            pnl_pct       = (current_value / cost_basis - 1.0) if cost_basis > 0 else 0.0
            weight        = current_value / total_value_mxn if total_value_mxn > 0 else 0.0

            if pnl_pct < STOP_LOSS:
                sell_signals.append({
                    "ticker": ticker, "broker": broker,
                    "action": "🚨 VENDER TODO",
                    "reason": f"Stop-loss: {pnl_pct:+.1%}",
                    "shares": shares, "pnl": pnl_pct, "weight": weight,
                    "urgency": "ALTA", "emoji": "🚨"
                })
            elif pnl_pct > TAKE_PROFIT:
                sell_signals.append({
                    "ticker": ticker, "broker": broker,
                    "action": "💰 VENDER 30%",
                    "reason": f"Take-profit: {pnl_pct:+.1%}",
                    "shares": math.floor(shares * 0.30),
                    "pnl": pnl_pct, "weight": weight,
                    "urgency": "MEDIA", "emoji": "💰"
                })
            elif weight > REBALANCE:
                excess = weight - REBALANCE
                sell_signals.append({
                    "ticker": ticker, "broker": broker,
                    "action": "⚖️ REBALANCEAR",
                    "reason": f"Sobreexposición: {weight:.1%}",
                    "shares": math.floor(shares * (excess / weight)),
                    "pnl": pnl_pct, "weight": weight,
                    "urgency": "BAJA", "emoji": "⚖️"
                })

    urgency_order = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
    sell_signals.sort(key=lambda x: urgency_order.get(x["urgency"], 3))
    return sell_signals

# ════════════════════════════════════════════════════════════════
# REPORTE COMPLETO (90% activos + 10% crypto)
# ════════════════════════════════════════════════════════════════

def _run_full_report_sync(budget_mxn: float):
    """Genera reporte completo con split 90% activos / 10% crypto."""

    budget_crypto = round(budget_mxn * CRYPTO_BUDGET_PCT, 2)
    budget_assets = round(budget_mxn * (1 - CRYPTO_BUDGET_PCT), 2)

    print(f"\n💰 Budget total : ${budget_mxn:,.2f} MXN")
    print(f"   Activos (90%) : ${budget_assets:,.2f} MXN")
    print(f"   Crypto  (10%) : ${budget_crypto:,.2f} MXN\n")

    universe,  _ = github_get_file("data/universe.json")
    portfolio, _ = github_get_file("data/portfolio.json")

    if not portfolio or not portfolio.get("accounts"):
        return {"success": False, "error": "No hay portafolio guardado"}
    if not universe:
        return {"success": False, "error": "No se pudo cargar universe.json"}

    # ── Datos de mercado (activos tradicionales) ──────────────────
    market_data = _get_market_data_sync(universe, max_workers=5, timeout_per_ticker=15)

    for item in universe:
        ticker   = item["ticker"]
        y_ticker = item["yahoo"]
        if ticker not in market_data:
            continue
        data = market_data[ticker]
        if not data.get("price") or not data.get("ret_3m"):
            data["vol_3m"] = None
            data["score"]  = None
            continue
        try:
            hist  = yf.Ticker(y_ticker).history(period="6mo")
            if hist is None or hist.empty:
                data["vol_3m"] = None; data["score"] = None; continue
            close  = hist["Close"].dropna()
            window = 63
            if len(close) < window + 1:
                data["vol_3m"] = None; data["score"] = None; continue
            close_3m  = close.iloc[-(window + 1):]
            daily_ret = close_3m.pct_change().dropna()
            vol_3m    = float(daily_ret.std() * math.sqrt(window))
            score     = (data["ret_3m"] / vol_3m) if vol_3m and vol_3m > 0 else None
            data["vol_3m"] = vol_3m
            data["score"]  = score
        except:
            data["vol_3m"] = None
            data["score"]  = None

    # ── Plan de compra activos ─────────────────────────────────────
    owned_tickers = []
    for broker, acc in portfolio.get("accounts", {}).items():
        for h in acc.get("holdings", []):
            owned_tickers.append(h["ticker"])

    all_with_score = []
    for ticker, data in market_data.items():
        if data.get("price") and data.get("score"):
            all_with_score.append((ticker, data["score"], ticker in owned_tickers))
    all_with_score.sort(key=lambda x: x[1], reverse=True)

    owned_buy = [t for t, s, o in all_with_score if o][:3]
    new_buy   = [t for t, s, o in all_with_score if not o][:3]
    chosen    = owned_buy + new_buy

    plan = {"GBM": {}, "Bitso": {}}
    if chosen and budget_assets > 0:
        per_ticker = budget_assets / len(chosen)
        broker_map = {x["ticker"]: x["broker"] for x in universe}
        type_map   = {x["ticker"]: x["type"]   for x in universe}
        for ticker in chosen:
            broker     = broker_map.get(ticker, "GBM")
            asset_type = type_map.get(ticker, "STOCK")
            price      = market_data.get(ticker, {}).get("price")
            if not price:
                continue
            if broker == "GBM":
                qty = math.floor(per_ticker / price)
                plan["GBM"][ticker] = {"type": asset_type, "amount_mxn": round(per_ticker, 2),
                                       "shares": int(qty), "price": price}
            else:
                plan["Bitso"][ticker] = {"type": asset_type, "amount_mxn": round(per_ticker, 2),
                                         "shares": None, "price": price}

    # ── Tipo de cambio y datos crypto ─────────────────────────────
    usd_to_mxn  = get_usd_to_mxn()
    crypto_data = get_crypto_data_sync(usd_to_mxn)

    crypto_result = get_crypto_recommendation_sync(
        crypto_data   = crypto_data,
        budget_crypto = budget_crypto,
        usd_to_mxn    = usd_to_mxn,
        portfolio     = portfolio,
    )

    # ── Análisis IA ───────────────────────────────────────────────
    analysis = "⚠️ OpenAI no configurado - Sin análisis de IA"

    if client_openai:
        context = {
            "fecha":          datetime.utcnow().isoformat(),
            "budget_total":   budget_mxn,
            "budget_assets":  budget_assets,
            "budget_crypto":  budget_crypto,
            "chosen":         chosen,
            "owned_buy":      owned_buy,
            "new_buy":        new_buy,
            "market_data":    {k: {kk: vv for kk, vv in v.items()} for k, v in market_data.items()},
            "plan":           plan,
            "crypto_plan":    crypto_result.get("plan", {}),
        }

        prompt = f"""
Eres analista financiero experto en inversión pasiva para inversionistas mexicanos.
Genera un reporte quincenal que incluye activos tradicionales Y criptomonedas.

Presupuesto total: ${budget_mxn:,.2f} MXN
  └─ Activos (90%): ${budget_assets:,.2f} MXN
  └─ Crypto  (10%): ${budget_crypto:,.2f} MXN

DATOS:
{json.dumps(context, ensure_ascii=False, indent=2)}

FORMATO (máximo 1000 palabras):

## 📊 Resumen Ejecutivo
[2 párrafos: contexto de mercado y estrategia del periodo]

## 💰 Plan — Activos Tradicionales (90%)
[Cada activo: score, retorno 3M, razón de selección]

## ₿ Plan — Crypto (10%)
[Cryptos recomendadas, razón para ESTE perfil específico]
[Nota: mantener crypto en 10% máximo por volatilidad]

## 🎯 Top 3 PRIORIZAR / Top 3 EVITAR
[Con scores]

## ⚠️ Consideraciones
[Riesgos del periodo, limitaciones del análisis]

REGLAS: NO prometas rendimientos. USA solo datos del JSON. Sé específico con números.
"""
        try:
            resp     = client_openai.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "Eres analista financiero experto en portafolios mixtos con crypto."},
                    {"role": "user",   "content": prompt}
                ],
                max_completion_tokens=4000,
                temperature=0.3,
            )
            analysis = resp.choices[0].message.content
        except Exception as e:
            analysis = f"⚠️ Error generando análisis: {str(e)}"

    return {
        "success":         True,
        "plan":            plan,
        "chosen":          chosen,
        "owned_buy":       owned_buy,
        "new_buy":         new_buy,
        "market_data":     market_data,
        "analysis":        analysis,
        "budget_assets":   budget_assets,
        "budget_crypto":   budget_crypto,
        "crypto_plan":     crypto_result.get("plan", {}),
        "crypto_strategy": crypto_result.get("strategy_summary", ""),
        "crypto_warning":  crypto_result.get("warning", ""),
        "usd_to_mxn":      usd_to_mxn,
    }

# ════════════════════════════════════════════════════════════════
# COMANDOS
# ════════════════════════════════════════════════════════════════

@bot.command(name="reporte")
async def report(ctx, presupuesto: float):
    """Reporte quincenal: 90% activos tradicionales + 10% crypto"""

    if presupuesto < 100:
        await ctx.send("❌ Presupuesto mínimo: $100 MXN")
        return

    budget_crypto = round(presupuesto * CRYPTO_BUDGET_PCT, 2)
    budget_assets = round(presupuesto * (1 - CRYPTO_BUDGET_PCT), 2)

    initial_msg = await ctx.send(
        f"📊 **Generando reporte — ${presupuesto:,.2f} MXN**\n\n"
        f"├─ 💼 Activos (90%): ${budget_assets:,.2f} MXN\n"
        f"└─ ₿  Crypto  (10%): ${budget_crypto:,.2f} MXN\n\n"
        f"⏳ Procesando... (~2-3 min)"
    )

    try:
        import asyncio
        loop = asyncio.get_event_loop()

        loading_msgs = [
            "📡 Descargando precios de activos...",
            "₿  Descargando precios de crypto...",
            "🤖 IA analizando tu perfil...",
            "📝 Armando reporte final...",
        ]

        async def update_status():
            i = 0
            while True:
                await asyncio.sleep(15)
                try:
                    await initial_msg.edit(
                        content=(
                            f"📊 **Generando reporte** — ${presupuesto:,.2f} MXN\n"
                            f"{loading_msgs[i % len(loading_msgs)]}"
                        )
                    )
                    i += 1
                except:
                    break

        status_task = asyncio.create_task(update_status())
        result      = await loop.run_in_executor(None, _run_full_report_sync, presupuesto)
        status_task.cancel()

        if not result["success"]:
            await initial_msg.edit(content=f"❌ Error: {result.get('error', 'Desconocido')}")
            return

        await initial_msg.edit(content="✅ **Reporte listo**")

        # ── 1. Header ─────────────────────────────────────────────
        chosen    = result["chosen"]
        owned_buy = result["owned_buy"]
        new_buy   = result["new_buy"]

        header  = f"🔔 **REPORTE QUINCENAL** — {datetime.now().strftime('%d/%m/%Y')}\n\n"
        header += f"💰 **Presupuesto total:** ${presupuesto:,.2f} MXN\n"
        header += f"├─ 💼 Activos (90%): ${result['budget_assets']:,.2f} MXN\n"
        header += f"└─ ₿  Crypto  (10%): ${result['budget_crypto']:,.2f} MXN\n\n"
        if owned_buy:
            header += f"🔄 **Recompra:** {', '.join(owned_buy)}\n"
        if new_buy:
            header += f"✨ **Nuevos activos:** {', '.join(new_buy)}\n"
        await ctx.send(header)

        # ── 2. Plan activos tradicionales ─────────────────────────
        plan        = result["plan"]
        total_gbm   = 0
        total_bitso = 0

        plan_msg  = "```\n"
        plan_msg += "══════════════════════════════════════════\n"
        plan_msg += "   💼 PLAN — ACTIVOS TRADICIONALES (90%)\n"
        plan_msg += "══════════════════════════════════════════\n\n"

        if plan["GBM"]:
            plan_msg += "🏦 GBM (FIBRAs — títulos enteros)\n"
            plan_msg += "──────────────────────────────────────────\n"
            for ticker, data in plan["GBM"].items():
                s = data["shares"]; p = data["price"]; t = s * p
                total_gbm += t
                plan_msg += f"  • {ticker:12} {s:3} tít @ ${p:8.2f} = ${t:9.2f}\n"
            plan_msg += f"  {'─'*40}\n"
            plan_msg += f"  Total GBM   : ${total_gbm:,.2f} MXN\n\n"

        if plan["Bitso"]:
            plan_msg += "📈 Bitso (Acciones/ETFs — fraccional)\n"
            plan_msg += "──────────────────────────────────────────\n"
            for ticker, data in plan["Bitso"].items():
                amt = data["amount_mxn"]; total_bitso += amt
                plan_msg += f"  • {ticker:12} ${amt:9.2f} MXN\n"
            plan_msg += f"  {'─'*40}\n"
            plan_msg += f"  Total Bitso : ${total_bitso:,.2f} MXN\n"

        plan_msg += "\n══════════════════════════════════════════\n"
        plan_msg += f"  Subtotal activos: ${total_gbm + total_bitso:,.2f} MXN\n"
        plan_msg += "══════════════════════════════════════════\n```"
        await ctx.send(plan_msg)

        # ── 3. Plan crypto ────────────────────────────────────────
        crypto_plan = result.get("crypto_plan", {})

        if crypto_plan:
            total_crypto = sum(d["amount_mxn"] for d in crypto_plan.values())

            c_msg  = "```\n"
            c_msg += "══════════════════════════════════════════\n"
            c_msg += "   ₿  PLAN — CRYPTO  (10% del presupuesto)\n"
            c_msg += "══════════════════════════════════════════\n\n"
            c_msg += "  📍 Broker: Bitso (compra fraccional en MXN)\n\n"

            for ticker, data in crypto_plan.items():
                amt  = data["amount_mxn"]
                qty  = data["qty_crypto"]
                pusd = data["price_usd"]
                pct  = data["allocation_pct"]
                risk = data["risk_level"]
                raz  = data["reason"][:75]

                c_msg += f"  ₿ {ticker}  ({pct}% del budget crypto)\n"
                c_msg += f"    Monto   : ${amt:,.2f} MXN  (~${data['amount_usd']:,.2f} USD)\n"
                c_msg += f"    Cantidad: {qty:.8f} {ticker}\n"
                c_msg += f"    Precio  : ${pusd:,.2f} USD\n"
                c_msg += f"    Riesgo  : {risk}\n"
                c_msg += f"    Razón   : {raz}\n\n"

            total_general = total_gbm + total_bitso + total_crypto
            c_msg += f"  {'─'*40}\n"
            c_msg += f"  Total Crypto  : ${total_crypto:,.2f} MXN\n"
            c_msg += "══════════════════════════════════════════\n"
            c_msg += f"  TOTAL GENERAL : ${total_general:,.2f} MXN\n"
            c_msg += "══════════════════════════════════════════\n```"
            await ctx.send(c_msg)

            strategy = result.get("crypto_strategy", "")
            warning  = result.get("crypto_warning", "")
            if strategy:
                await ctx.send(
                    f"₿ **Estrategia Crypto:**\n_{strategy}_\n\n"
                    f"⚠️ _{warning}_"
                )

        # ── 4. Análisis IA completo ───────────────────────────────
        analysis = result.get("analysis", "No disponible")
        await ctx.send("🤖 **ANÁLISIS COMPLETO**")
        chunks = [analysis[i:i+1900] for i in range(0, len(analysis), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

        # ── 5. Cierre ─────────────────────────────────────────────
        await ctx.send(
            "\n**Después de comprar, actualiza tu portafolio:**\n"
            "`!comprar TICKER CANTIDAD PRECIO`\n\n"
            "⚠️ _Crypto es la parte más volátil — mantener máximo 10%_"
        )

    except Exception as e:
        try:
            await initial_msg.edit(content="❌ **Error generando reporte**")
        except:
            pass
        await ctx.send(f"```\n{str(e)}\n```")
        traceback.print_exc()


@bot.command(name="debug")
async def debug_ticker(ctx, ticker_input: str):
    ticker_input = ticker_input.upper()
    await ctx.send(f"🔍 Analizando {ticker_input}...")
    portfolio, _ = github_get_file("data/portfolio.json")
    universe, _  = github_get_file("data/universe.json")
    if not portfolio or not universe:
        await ctx.send("❌ Error cargando archivos"); return
    holding = None; broker_found = None
    for broker, acc in portfolio.get("accounts", {}).items():
        for h in acc.get("holdings", []):
            if h["ticker"] == ticker_input:
                holding = h; broker_found = broker; break
    if not holding:
        await ctx.send(f"❌ {ticker_input} no está en tu portafolio"); return
    yahoo_ticker = None
    for item in universe:
        if item.get("ticker") == ticker_input:
            yahoo_ticker = item.get("yahoo"); break
    if not yahoo_ticker:
        await ctx.send(f"❌ {ticker_input} no está en universe.json"); return
    shares = float(holding["shares"]); avg_cost = float(holding["avg_cost"])
    t = yf.Ticker(yahoo_ticker)
    msg = f"```\n═══ DEBUG: {ticker_input} ═══\n"
    msg += f"Yahoo: {yahoo_ticker} | Broker: {broker_found}\n"
    msg += f"Shares: {shares} | Avg cost: ${avg_cost:.2f} MXN\n\n"
    try:
        p = t.fast_info.last_price
        msg += f"fast_info: ${p:.4f}\n"
    except Exception as e:
        msg += f"fast_info: ERROR\n"
    usd_to_mxn = get_usd_to_mxn()
    precio = get_price_with_retry(yahoo_ticker)
    if precio:
        p_mxn = precio if yahoo_ticker.endswith(".MX") else precio * usd_to_mxn
        cb    = shares * avg_cost
        cv    = shares * p_mxn
        pnl   = (cv / cb - 1.0) if cb > 0 else 0
        msg += f"\nPrecio usado: ${p_mxn:.4f} MXN\n"
        msg += f"Valor actual: ${cv:,.2f} MXN\n"
        msg += f"Costo base  : ${cb:,.2f} MXN\n"
        msg += f"P&L         : {pnl:+.2%}\n"
    msg += "```"
    await ctx.send(msg)


@bot.command(name="debug_total")
async def debug_total(ctx):
    await ctx.send("⏳ Calculando valor total...")
    portfolio, _ = github_get_file("data/portfolio.json")
    universe, _  = github_get_file("data/universe.json")
    if not portfolio or not universe:
        await ctx.send("❌ Error cargando archivos"); return
    yahoo_map  = {item["ticker"]: item["yahoo"] for item in universe}
    usd_to_mxn = get_usd_to_mxn()
    import asyncio
    loop = asyncio.get_event_loop()
    market_data = await loop.run_in_executor(None, _get_market_data_sync, universe, 5, 15)
    rows = []; total = 0.0
    for broker, acc in portfolio.get("accounts", {}).items():
        for h in acc.get("holdings", []):
            ticker       = h["ticker"]
            shares       = float(h["shares"])
            avg_cost     = float(h["avg_cost"])
            yahoo_ticker = yahoo_map.get(ticker, "")
            data         = market_data.get(ticker, {})
            price_raw    = data.get("price")
            if price_raw:
                p_mxn = price_raw if yahoo_ticker.endswith(".MX") else price_raw * usd_to_mxn
                valor = shares * p_mxn; has_p = True
            else:
                p_mxn = avg_cost; valor = shares * avg_cost; has_p = False
            total += valor
            rows.append((ticker, broker, valor, valor/max(total,1), "✅" if has_p else "❌"))
    msg = "```\n" + f"{'Ticker':<12} {'Broker':<8} {'Valor MXN':>10} {'Peso':>7} {'Precio?':>8}\n" + "─"*50 + "\n"
    for t, b, v, w, icon in rows:
        msg += f"{t:<12} {b:<8} ${v:>8,.0f}  {w:>6.1%}  {icon}\n"
    msg += f"{'─'*50}\n{'TOTAL':<12} {'':8} ${total:>8,.0f}\n```"
    await ctx.send(msg)


@bot.command(name="señales")
async def sell_signals(ctx):
    await ctx.send("⏳ Analizando tu portafolio...")
    portfolio, _ = github_get_file("data/portfolio.json")
    if not portfolio:
        await ctx.send("❌ Error descargando portfolio"); return
    signals = await evaluate_sells(portfolio)
    if not signals:
        embed = discord.Embed(title="✅ TODO BIEN", description="No hay señales de venta.", color=discord.Color.green())
        await ctx.send(embed=embed); return
    embed = discord.Embed(title="⚠️ SEÑALES DE VENTA",
                          description=f"**{len(signals)}** activos para revisar:",
                          color=discord.Color.orange())
    for s in signals:
        uc = {"ALTA": "🔴", "MEDIA": "🟡", "BAJA": "🟢"}.get(s["urgency"], "⚪")
        embed.add_field(
            name=f"{s['emoji']} {s['ticker']} — {s['action']}",
            value=(f"{uc} **Urgencia:** {s['urgency']}\n"
                   f"📊 **P&L:** {s['pnl']:+.1%} | ⚖️ **Peso:** {s['weight']:.1%}\n"
                   f"🔢 **Vender:** {s['shares']:.3f} títulos\n"
                   f"📝 {s['reason']}"),
            inline=False
        )
    embed.set_footer(text="Tú decides. Actualiza con: !vender TICKER CANTIDAD")
    await ctx.send(embed=embed)


@bot.command(name="balance")
async def portfolio_balance(ctx):
    await ctx.send("⏳ Calculando tu balance...")
    portfolio, _ = github_get_file("data/portfolio.json")
    if not portfolio:
        await ctx.send("❌ Error descargando portfolio"); return
    universe, _ = github_get_file("data/universe.json")
    if not universe:
        await ctx.send("❌ Error descargando universe.json"); return
    yahoo_map  = {item["ticker"]: item["yahoo"] for item in universe if item.get("ticker") and item.get("yahoo")}
    tipo_cambio = get_usd_to_mxn()
    await ctx.send("📊 Descargando precios actuales...")
    precios_mxn = {}
    for broker, cuenta in portfolio.get("accounts", {}).items():
        for holding in cuenta.get("holdings", []):
            ticker = holding["ticker"]
            yahoo_ticker = yahoo_map.get(ticker)
            if not yahoo_ticker:
                continue
            try:
                price, currency = get_last_close_and_currency(yahoo_ticker)
                precios_mxn[ticker] = to_mxn(price, currency, tipo_cambio) if price else None
            except:
                precios_mxn[ticker] = None
    total_invertido = 0.0; total_actual = 0.0; detalles = []
    for broker, cuenta in portfolio.get("accounts", {}).items():
        for holding in cuenta.get("holdings", []):
            ticker   = holding["ticker"]
            shares   = float(holding.get("shares", 0))
            avg_cost = float(holding.get("avg_cost", 0))
            precio_actual = precios_mxn.get(ticker)
            if precio_actual is None:
                continue
            di = shares * avg_cost; va = shares * precio_actual
            gp = va - di; pct = (gp / di * 100) if di > 0 else 0
            total_invertido += di; total_actual += va
            detalles.append({"ticker": ticker, "broker": broker,
                              "invertido": di, "actual": va,
                              "ganancia": gp, "porcentaje": pct})
    pnl_total = total_actual - total_invertido
    pnl_pct   = (pnl_total / total_invertido * 100) if total_invertido > 0 else 0
    ganadores  = sorted([d for d in detalles if d["ganancia"] > 0],  key=lambda x: x["ganancia"], reverse=True)
    perdedores = sorted([d for d in detalles if d["ganancia"] < 0],  key=lambda x: x["ganancia"])
    color = discord.Color.green() if pnl_total >= 0 else discord.Color.red()
    embed = discord.Embed(title="📊 BALANCE DE TU PORTAFOLIO", color=color)
    embed.add_field(name="💰 Resumen General",
                    value=(f"**Inversión total:** ${total_invertido:,.2f} MXN\n"
                           f"**Valor actual:** ${total_actual:,.2f} MXN\n"
                           f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                           f"**P&L Total:** ${pnl_total:+,.2f} ({pnl_pct:+.2f}%)"), inline=False)
    if ganadores:
        embed.add_field(name=f"✅ Ganancias ({len(ganadores)})",
                        value=f"**${sum(d['ganancia'] for d in ganadores):,.2f}** MXN", inline=True)
    if perdedores:
        embed.add_field(name=f"❌ Pérdidas ({len(perdedores)})",
                        value=f"**${sum(d['ganancia'] for d in perdedores):,.2f}** MXN", inline=True)
    if ganadores:
        embed.add_field(name="🏆 Top 3 Ganadores",
                        value="\n".join([f"**{d['ticker']}**: ${d['ganancia']:+,.2f} ({d['porcentaje']:+.2f}%)"
                                         for d in ganadores[:3]]), inline=False)
    if perdedores:
        embed.add_field(name="📉 Top 3 Perdedores",
                        value="\n".join([f"**{d['ticker']}**: ${d['ganancia']:+,.2f} ({d['porcentaje']:+.2f}%)"
                                         for d in perdedores[:3]]), inline=False)
    await ctx.send(embed=embed)


@bot.command(name="portafolio")
async def show_portfolio(ctx):
    await ctx.send("⏳ Descargando tu portafolio...")
    portfolio, _ = github_get_file("data/portfolio.json")
    if not portfolio:
        await ctx.send("❌ Error al descargar tu portafolio"); return
    embed = discord.Embed(title="📊 TU PORTAFOLIO", color=discord.Color.blue())
    for broker, acc in portfolio.get("accounts", {}).items():
        text = ""
        for h in acc.get("holdings", []):
            text += f"`{h['ticker']:12}` {h['shares']:>8.3f} @ ${h['avg_cost']:>8.2f}\n"
        embed.add_field(name=f"{'🏦' if broker == 'GBM' else '📈'} {broker}",
                        value=text or "Vacío", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="vender")
async def sell(ctx, ticker: str, shares: float):
    await ctx.send(f"⏳ Procesando venta de {shares} {ticker.upper()}...")
    portfolio, sha = github_get_file("data/portfolio.json")
    if not portfolio:
        await ctx.send("❌ Error descargando portfolio"); return
    ticker = ticker.upper(); found = False
    for broker, acc in portfolio["accounts"].items():
        for i, h in enumerate(acc["holdings"]):
            if h["ticker"] == ticker:
                old = h["shares"]; new = old - shares
                if new <= 0:
                    portfolio["accounts"][broker]["holdings"].pop(i)
                    await ctx.send(f"🗑️ **{ticker} vendido completamente** ({old} → 0)")
                else:
                    portfolio["accounts"][broker]["holdings"][i]["shares"] = round(new, 3)
                    await ctx.send(f"📉 **{ticker}** Shares: {old} → {new}")
                found = True; break
        if found: break
    if not found:
        await ctx.send(f"⚠️ {ticker} no encontrado"); return
    if github_save_file("data/portfolio.json", portfolio, sha, f"💱 Sell {ticker}"):
        await ctx.send("✅ Portfolio actualizado en GitHub")
    else:
        await ctx.send("❌ Error guardando. Usa `!test_github`")


@bot.command(name="comprar")
async def buy(ctx, ticker: str, shares: float, price: float, broker: str = None):
    ticker = ticker.upper()
    await ctx.send(f"⏳ Procesando compra de {shares} {ticker} @ ${price}...")
    portfolio, sha = github_get_file("data/portfolio.json")
    if not portfolio:
        await ctx.send("❌ Error descargando portfolio"); return
    if not broker:
        universe, _ = github_get_file("data/universe.json")
        if universe:
            for item in universe:
                if item.get("ticker") == ticker:
                    broker = item.get("broker", "GBM"); break
        if not broker:
            await ctx.send(f"⚠️ Especifica broker: `!comprar {ticker} {shares} {price} GBM`"); return
    broker = "GBM" if broker.upper() == "GBM" else "Bitso"
    if broker not in portfolio.get("accounts", {}):
        portfolio["accounts"][broker] = {"currency": "MXN", "holdings": []}
    found = False
    for i, h in enumerate(portfolio["accounts"][broker]["holdings"]):
        if h["ticker"] == ticker:
            os_ = h["shares"]; oc = h["avg_cost"]
            ts  = os_ + shares; tv = (os_ * oc) + (shares * price); na = tv / ts
            portfolio["accounts"][broker]["holdings"][i]["shares"]   = round(ts, 3)
            portfolio["accounts"][broker]["holdings"][i]["avg_cost"] = round(na, 2)
            await ctx.send(f"📈 **{ticker}** Shares: {os_:.3f}→{ts:.3f} | Avg: ${oc:.2f}→${na:.2f}")
            found = True; break
    if not found:
        universe, _ = github_get_file("data/universe.json")
        asset_type  = "STOCK"
        if universe:
            for item in universe:
                if item.get("ticker") == ticker:
                    asset_type = item.get("type", "STOCK"); break
        portfolio["accounts"][broker]["holdings"].append({
            "ticker": ticker, "type": asset_type,
            "shares": round(shares, 3), "avg_cost": round(price, 2)
        })
        await ctx.send(f"✨ **Nuevo holding:** {ticker} ({asset_type}) en {broker}")
    if github_save_file("data/portfolio.json", portfolio, sha, f"💱 Buy {ticker}"):
        await ctx.send("✅ Portfolio actualizado en GitHub")
    else:
        await ctx.send("❌ Error guardando. Usa `!test_github`")


@bot.command(name="test_github")
async def test_github(ctx):
    embed = discord.Embed(title="🔧 DIAGNÓSTICO GITHUB", color=discord.Color.blue())
    embed.add_field(name="Variables",
                    value=(f"GB_REPO: {'✅ `' + GITHUB_REPO + '`' if GITHUB_REPO else '❌ NO CONFIGURADO'}\n"
                           f"GB_TOKEN: {'✅ Configurado' if GITHUB_TOKEN else '❌ NO CONFIGURADO'}"), inline=False)
    if not GITHUB_REPO or not GITHUB_TOKEN:
        embed.add_field(name="❌ Configuración incompleta",
                        value="Agrega GB_REPO y GB_TOKEN en Railway → Variables", inline=False)
        await ctx.send(embed=embed); return
    portfolio, sha = github_get_file("data/portfolio.json")
    if portfolio:
        embed.add_field(name="Lectura", value=f"✅ portfolio.json descargado (SHA: `{sha[:10]}...`)", inline=False)
    else:
        embed.add_field(name="Lectura", value="❌ Error descargando portfolio.json", inline=False)
        await ctx.send(embed=embed); return
    ok = github_save_file("data/portfolio.json", portfolio, sha, "🔧 Test permisos")
    embed.add_field(name="Escritura", value="✅ Token con permisos de escritura" if ok else
                    "❌ Token SIN escritura → genera nuevo token con scope 'repo'", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="discover")
async def discover_cmd(ctx, cantidad: int = 6):
    await ctx.send(f"🔍 Descubriendo {cantidad} nuevos activos...")
    if discover_assets(max_assets=cantidad, mode="suggest"):
        wait_msg = await ctx.send("✅ Workflow iniciado. Esperando resultados (~60s)...")
        import asyncio
        for attempt in range(7):
            await asyncio.sleep(10)
            metadata, _ = github_get_file("data/discover_metadata.json")
            if metadata:
                pending = metadata.get("pending_suggestions", [])
                last    = metadata.get("last_discover", "")
                try:
                    from datetime import timedelta
                    dt = datetime.fromisoformat(last)
                    if (datetime.now() - dt) < timedelta(minutes=2) and pending:
                        break
                except:
                    pass
            remaining = (6 - attempt) * 10
            if remaining > 0:
                await wait_msg.edit(content=f"⏳ Esperando... (~{remaining}s)")
        metadata, _ = github_get_file("data/discover_metadata.json")
        if not metadata:
            await ctx.send("⚠️ No se pudo cargar metadata. Usa `!discover_status`"); return
        pending = metadata.get("pending_suggestions", [])
        if not pending:
            await ctx.send("⚠️ Sin sugerencias nuevas. Intenta de nuevo."); return
        embed = discord.Embed(title="✨ NUEVOS ACTIVOS SUGERIDOS",
                              description=f"**{len(pending)}** instrumentos encontrados:",
                              color=discord.Color.green())
        by_type = {"FIBRA": [], "ETF": [], "STOCK": []}
        for asset in pending:
            by_type[asset.get("type", "STOCK")].append(asset)
        for tipo, emoji, title in [("FIBRA","🏢","FIBRAs"),("ETF","📈","ETFs"),("STOCK","💼","Acciones")]:
            if by_type[tipo]:
                text = "\n".join([f"**{a['ticker']}** ({a['broker']})\n└ {a['reason']}" for a in by_type[tipo]])
                if len(text) > 1024: text = text[:1020] + "..."
                embed.add_field(name=f"{emoji} {title}", value=text, inline=False)
        await ctx.send(embed=embed)
        await ctx.send("Para agregar: `!discover_commit`")
    else:
        await ctx.send("❌ Error ejecutando discover")


@bot.command(name="discover_commit")
async def discover_commit(ctx):
    metadata, meta_sha = github_get_file("data/discover_metadata.json")
    if not metadata:
        await ctx.send("❌ No se pudo cargar metadata"); return
    pending = metadata.get("pending_suggestions", [])
    if not pending:
        await ctx.send("⚠️ No hay sugerencias pendientes. Ejecuta `!discover [n]` primero"); return
    valid = [a for a in pending if isinstance(a, dict) and all([a.get("ticker"), a.get("yahoo"), a.get("broker"), a.get("type")])]
    if not valid:
        await ctx.send("❌ No hay sugerencias válidas"); return
    universe, uni_sha = github_get_file("data/universe.json")
    if not universe or not isinstance(universe, list):
        await ctx.send("❌ Error cargando universe.json"); return
    current = {item.get("ticker") for item in universe}
    added   = [a for a in valid if a["ticker"] not in current]
    if not added:
        await ctx.send("⚠️ Todos ya estaban en el universo"); return
    universe.extend(added)
    if github_save_file("data/universe.json", universe, uni_sha, f"✅ Added {len(added)} assets"):
        metadata["pending_suggestions"] = []
        github_save_file("data/discover_metadata.json", metadata, meta_sha, "🧹 Clear pending")
        embed = discord.Embed(title="✅ INSTRUMENTOS AGREGADOS",
                              description=f"**{len(added)}** agregados al universo ({len(universe)} total)",
                              color=discord.Color.green())
        for a in added:
            embed.add_field(name=f"• {a['ticker']} ({a['type']})", value=a.get("reason", ""), inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Error guardando cambios")


@bot.command(name="discover_status")
async def discover_status(ctx):
    metadata, _ = github_get_file("data/discover_metadata.json")
    if not metadata:
        await ctx.send("❌ No hay metadata de discover"); return
    pending = metadata.get("pending_suggestions", [])
    embed = discord.Embed(title="📊 ESTADO DE DISCOVER", color=discord.Color.blue())
    embed.add_field(name="⏰ Último discover", value=metadata.get("last_discover", "Nunca")[:19], inline=False)
    embed.add_field(name="📋 Pendientes", value=f"**{len(pending)}** instrumentos", inline=False)
    if pending:
        embed.add_field(name="Acciones", value="`!discover_commit` — aprobar\n`!discover 6` — generar nuevas", inline=False)
    await ctx.send(embed=embed)


def discover_assets(max_assets: int = 6, mode: str = "suggest"):
    if not GITHUB_REPO or not GITHUB_TOKEN:
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/discover_assets.yml/dispatches"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        resp = requests.post(url, headers=headers,
                             json={"ref": "main", "inputs": {"mode": mode, "max_assets": str(max_assets)}},
                             timeout=10)
        return resp.status_code == 204
    except:
        return False

# ════════════════════════════════════════════════════════════════
# AUTOMATIZACIÓN
# ════════════════════════════════════════════════════════════════

@tasks.loop(time=time(hour=15, minute=0))
async def scheduled_report():
    global last_report_day
    try:
        now = datetime.utcnow()
        day = now.day
        if last_report_day == (now.year, now.month, day):
            return
        if day not in [1, 16]:
            return
        if not CHANNEL_ID:
            return
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            return
        last_report_day = (now.year, now.month, day)
        await channel.send(f"🔔 **REPORTE AUTOMÁTICO — {now.strftime('%d/%m/%Y')}**")
        portfolio, _ = github_get_file("data/portfolio.json")
        if not portfolio:
            await channel.send("❌ Error descargando portfolio"); return
        signals = await evaluate_sells(portfolio)
        if signals:
            embed = discord.Embed(title="⚠️ SEÑALES DE VENTA",
                                  description=f"**{len(signals)}** activos para revisar:",
                                  color=discord.Color.orange())
            for s in signals:
                embed.add_field(name=f"{s['emoji']} {s['ticker']} — {s['action']}",
                                value=f"P&L: {s['pnl']:+.1%} | Peso: {s['weight']:.1%}\n{s['reason']}",
                                inline=False)
            await channel.send(embed=embed)
            await channel.send("Cuando termines de revisar, responde: `listo`")
            def check(m): return m.channel == channel and m.author.id != bot.user.id
            try:
                msg = await bot.wait_for('message', check=check, timeout=3600)
                if not any(w in msg.content.lower() for w in ["listo", "siguiente", "continua"]):
                    await channel.send("⏸️ Flujo pausado"); return
            except:
                await channel.send("⏱️ Timeout. Usa `!reporte PRESUPUESTO` manualmente"); return
        else:
            await channel.send("✅ No hay señales de venta")
        await channel.send("💰 **¿Cuál es tu presupuesto para esta quincena?** (responde con el monto en MXN)")
        def check_budget(m):
            return m.channel == channel and m.author.id != bot.user.id and m.content.replace(".", "").replace(",", "").isdigit()
        try:
            msg    = await bot.wait_for('message', check=check_budget, timeout=3600)
            budget = float(msg.content.replace(",", ""))
            await channel.send(f"✅ Presupuesto: ${budget:,.2f} MXN")
        except:
            await channel.send("⏱️ Timeout. Usa `!reporte PRESUPUESTO` manualmente"); return
        await channel.send("📊 Generando reporte...")
        import asyncio
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_full_report_sync, budget)
        if not result["success"]:
            await channel.send(f"❌ Error: {result.get('error')}"); return
        await channel.send("✅ **Reporte completado**")
        chosen = result["chosen"]
        summary  = f"💰 **Presupuesto:** ${budget:,.2f} MXN | "
        summary += f"📊 **Activos (90%):** ${result['budget_assets']:,.2f} | "
        summary += f"₿ **Crypto (10%):** ${result['budget_crypto']:,.2f}\n"
        if result["owned_buy"]: summary += f"🔄 Recompra: {', '.join(result['owned_buy'])}\n"
        if result["new_buy"]:   summary += f"✨ Nuevos: {', '.join(result['new_buy'])}\n"
        await channel.send(summary)
        plan = result["plan"]
        plan_msg = "```\n📋 PLAN ACTIVOS\n"
        for ticker, data in plan["GBM"].items():
            plan_msg += f"GBM  • {ticker}: {data['shares']} títulos (${data['amount_mxn']:,.2f})\n"
        for ticker, data in plan["Bitso"].items():
            plan_msg += f"Bitso• {ticker}: ${data['amount_mxn']:,.2f}\n"
        plan_msg += "```"
        await channel.send(plan_msg)
        crypto_plan = result.get("crypto_plan", {})
        if crypto_plan:
            c_msg = "```\n₿ PLAN CRYPTO\n"
            for ticker, data in crypto_plan.items():
                c_msg += f"  {ticker}: ${data['amount_mxn']:,.2f} MXN ({data['allocation_pct']}%)\n"
            c_msg += "```"
            await channel.send(c_msg)
        analysis = result.get("analysis", "")
        if analysis:
            for chunk in [analysis[i:i+1900] for i in range(0, len(analysis), 1900)]:
                await channel.send(chunk)
    except Exception as e:
        print(f"❌ Error scheduled_report: {e}")
        traceback.print_exc()


@tasks.loop(time=time(hour=10, minute=0))
async def scheduled_discover():
    global last_discover_day
    try:
        now = datetime.utcnow()
        if last_discover_day == (now.year, now.month, now.day):
            return
        if now.day != 1 or not CHANNEL_ID:
            return
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            return
        last_discover_day = (now.year, now.month, now.day)
        await channel.send("🔍 **DISCOVER AUTOMÁTICO**")
        if discover_assets(max_assets=6, mode="suggest"):
            await channel.send("✅ Activos descubiertos. Aprueba con: `!discover_commit`")
    except Exception as e:
        print(f"❌ Error scheduled_discover: {e}")


@scheduled_report.error
async def scheduled_report_error(error):
    print(f"❌ scheduled_report error: {error}")

@scheduled_discover.error
async def scheduled_discover_error(error):
    print(f"❌ scheduled_discover error: {error}")

# ════════════════════════════════════════════════════════════════
# EVENTOS
# ════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"✅ Bot conectado: {bot.user}")
    print(f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   GB_REPO   : {'✓ ' + GITHUB_REPO if GITHUB_REPO else '✗ FALTANTE'}")
    print(f"   GB_TOKEN  : {'✓' if GITHUB_TOKEN else '✗ FALTANTE'}")
    print(f"   CHANNEL   : {'✓ ' + str(CHANNEL_ID) if CHANNEL_ID else '✗ FALTANTE'}")
    print(f"   OPENAI    : {'✓' if OPENAI_API_KEY else '✗ FALTANTE'}")
    print(f"₿  Crypto budget: {int(CRYPTO_BUDGET_PCT*100)}% del presupuesto")
    print("=" * 60)
    if not scheduled_report.is_running():
        scheduled_report.start()
    if not scheduled_discover.is_running():
        scheduled_discover.start()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Falta argumento. Usa `!help`")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Comando no existe. Usa `!help`")
    else:
        await ctx.send(f"❌ Error: {str(error)}")
        traceback.print_exc()


@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="🤖 COMANDOS — Investment Bot v4.0",
        description="₿ v4.0: 10% del presupuesto va a crypto recomendada por IA",
        color=discord.Color.green()
    )
    embed.add_field(name="📊 Consultas",
                    value="`!balance` `!portafolio` `!señales`", inline=False)
    embed.add_field(name="💰 Reporte (90% activos + 10% crypto)",
                    value="`!reporte PRESUPUESTO`\nEj: `!reporte 1500`", inline=False)
    embed.add_field(name="💱 Transacciones",
                    value="`!vender TICKER CANTIDAD`\n`!comprar TICKER CANTIDAD PRECIO [BROKER]`", inline=False)
    embed.add_field(name="🔍 Discover",
                    value="`!discover [n]` `!discover_commit` `!discover_status`", inline=False)
    embed.add_field(name="🔧 Debug",
                    value="`!debug TICKER` `!debug_total` `!test_github`", inline=False)
    embed.add_field(name="₿ Crypto Universe",
                    value="BTC · ETH · SOL · LINK · ADA · AVAX\n(IA elige 2 según tu perfil)", inline=False)
    embed.set_footer(text="Reportes automáticos: día 1 y 16 a las 15:00 UTC")
    await ctx.send(embed=embed)


# ════════════════════════════════════════════════════════════════
# INICIAR
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ FALTA DISCORD_BOT_TOKEN")
    elif not GITHUB_REPO:
        print("❌ FALTA GB_REPO")
    elif not GITHUB_TOKEN:
        print("❌ FALTA GB_TOKEN")
    else:
        print("🚀 Iniciando bot v4.0 con soporte crypto...")
        bot.run(BOT_TOKEN)