"""
🔍 Descubrimiento de nuevos instrumentos con IA (OPTIMIZADO)

MEJORAS v2:
- Prompt más detallado con contexto financiero
- Análisis de sectores faltantes
- Criterios de selección más estrictos
- Mejor validación de calidad
"""

import os
import json
import requests
from datetime import datetime
import yfinance as yf
from openai import OpenAI
import math


DATA_UNIVERSE = "data/universe.json"
DATA_PORTFOLIO = "data/portfolio.json"
DATA_DISCOVER_META = "data/discover_metadata.json"

OPENAI_MODEL = "gpt-5.2"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MODE = os.getenv("MODE", "suggest")

MAX_NEW_ASSETS = int(os.getenv("MAX_NEW_ASSETS", "6"))


def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {} if "portfolio" in path else []


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def send_discord(text: str):
    """Envía mensajes a Discord por webhook."""
    if not DISCORD_WEBHOOK_URL:
        print(f"[Discord] {text}")
        return
    if not text or not text.strip():
        return

    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    for c in chunks:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": c}, timeout=20)
        except Exception as e:
            print(f"Error enviando a Discord: {e}")


def validate_ticker(yahoo_ticker: str):
    """Valida que el ticker exista en Yahoo Finance"""
    try:
        ticker = yf.Ticker(yahoo_ticker)
        hist = ticker.history(period="1mo")
        if hist is None or hist.empty:
            return False
        return True
    except:
        return False


def analyze_portfolio_gaps(portfolio: dict, universe: list):
    """Analiza qué sectores y tipos de activos faltan en el portafolio"""
    
    holdings_by_type = {"FIBRA": [], "ETF": [], "STOCK": []}
    for broker, acc in portfolio.get("accounts", {}).items():
        for h in acc.get("holdings", []):
            tipo = h.get("type", "STOCK")
            holdings_by_type[tipo].append(h['ticker'])
    
    # Análisis detallado de sectores
    fibra_sectors = set()
    for ticker in holdings_by_type["FIBRA"]:
        if "FUNO" in ticker or "NOVA" in ticker:
            fibra_sectors.add("comercial/oficinas")
        elif "MTY" in ticker:
            fibra_sectors.add("industrial")
        elif "FIBRAPL" in ticker:
            fibra_sectors.add("logística")
        elif "DANHOS" in ticker:
            fibra_sectors.add("habitacional")
        elif "TERRA" in ticker or "FIBRAMQ" in ticker:
            fibra_sectors.add("industrial nearshoring")
        elif "FIHO" in ticker:
            fibra_sectors.add("hotelería")
        elif "FSHOP" in ticker:
            fibra_sectors.add("retail")
    
    fibra_gaps = []
    all_fibra_sectors = ["hotelería", "retail", "industrial nearshoring", "infraestructura", "educación"]
    for sector in all_fibra_sectors:
        if sector not in fibra_sectors:
            fibra_gaps.append(sector)
    
    etf_categories = set()
    for ticker in holdings_by_type["ETF"]:
        if ticker in ["QQQ", "XLK"]:
            etf_categories.add("tech")
        elif ticker in ["VTI", "VOO", "SPY"]:
            etf_categories.add("mercado total USA")
        elif ticker in ["SCHD", "VYM", "DVY"]:
            etf_categories.add("dividendos USA")
        elif ticker in ["VWO", "EEM", "IEMG"]:
            etf_categories.add("mercados emergentes")
        elif ticker in ["VNQ", "XLRE"]:
            etf_categories.add("REITs USA")
        elif ticker in ["VYMI", "VXUS"]:
            etf_categories.add("internacional ex-USA")
    
    etf_gaps = []
    all_etf_categories = ["dividendos USA", "mercados emergentes", "REITs USA", 
                          "internacional ex-USA", "small-cap", "value", "bonos"]
    for category in all_etf_categories:
        if category not in etf_categories:
            etf_gaps.append(category)
    
    stock_sectors = set()
    tech_stocks = ["GOOG", "GOOGL", "MSFT", "AAPL", "NVDA", "AVGO", "AMD"]
    finance_stocks = ["JPM", "BAC", "WFC", "GS", "MS"]
    health_stocks = ["UNH", "JNJ", "LLY", "ABBV", "TMO"]
    consumer_stocks = ["PG", "KO", "PEP", "WMT", "COST"]
    energy_stocks = ["XOM", "CVX", "COP", "SLB"]
    
    for ticker in holdings_by_type["STOCK"]:
        if ticker in tech_stocks:
            stock_sectors.add("tech")
        elif ticker in finance_stocks:
            stock_sectors.add("finanzas")
        elif ticker in health_stocks:
            stock_sectors.add("salud")
        elif ticker in consumer_stocks:
            stock_sectors.add("consumo")
        elif ticker in energy_stocks:
            stock_sectors.add("energía")
        elif ticker == "AMZN":
            stock_sectors.add("e-commerce")
    
    stock_gaps = []
    all_stock_sectors = ["salud", "finanzas", "consumo defensivo", "energía", 
                        "utilities", "materiales", "industriales"]
    for sector in all_stock_sectors:
        if sector not in stock_sectors:
            stock_gaps.append(sector)
    
    return {
        "fibra_sectors": list(fibra_sectors),
        "fibra_gaps": fibra_gaps,
        "etf_categories": list(etf_categories),
        "etf_gaps": etf_gaps,
        "stock_sectors": list(stock_sectors),
        "stock_gaps": stock_gaps,
        "holdings_by_type": holdings_by_type
    }


def discover_new_assets():
    """Usa IA para recomendar nuevos instrumentos con análisis mejorado"""
    
    portfolio = load_json(DATA_PORTFOLIO)
    universe = load_json(DATA_UNIVERSE)
    
    if not isinstance(universe, list):
        universe = []
    
    current_tickers = [item.get("ticker") for item in universe]
    
    # Análisis profundo del portafolio
    analysis = analyze_portfolio_gaps(portfolio, universe)
    
    # Calcular distribución
    num_fibras = MAX_NEW_ASSETS // 3
    num_etfs = MAX_NEW_ASSETS // 3
    num_stocks = MAX_NEW_ASSETS - num_fibras - num_etfs

    # PROMPT MEJORADO CON MÁS CONTEXTO
    prompt = f"""
Eres un asesor de inversión especializado en el mercado mexicano e internacional. Analiza este portafolio y recomienda diversificación inteligente.

═══════════════════════════════════════════════════════════════
📊 PORTAFOLIO ACTUAL DETALLADO
═══════════════════════════════════════════════════════════════

🏢 **FIBRAs Mexicanas ({len(analysis['holdings_by_type']['FIBRA'])}):**
Holdings: {', '.join(analysis['holdings_by_type']['FIBRA']) if analysis['holdings_by_type']['FIBRA'] else "NINGUNA"}
→ Sectores cubiertos: {', '.join(analysis['fibra_sectors']) if analysis['fibra_sectors'] else "ninguno"}
→ Sectores FALTANTES: {', '.join(analysis['fibra_gaps'][:5]) if analysis['fibra_gaps'] else "bien diversificado"}

📊 **ETFs Internacionales ({len(analysis['holdings_by_type']['ETF'])}):**
Holdings: {', '.join(analysis['holdings_by_type']['ETF']) if analysis['holdings_by_type']['ETF'] else "NINGUNO"}
→ Categorías cubiertas: {', '.join(analysis['etf_categories']) if analysis['etf_categories'] else "ninguna"}
→ Categorías FALTANTES: {', '.join(analysis['etf_gaps'][:5]) if analysis['etf_gaps'] else "bien diversificado"}

💼 **Acciones Individuales ({len(analysis['holdings_by_type']['STOCK'])}):**
Holdings: {', '.join(analysis['holdings_by_type']['STOCK']) if analysis['holdings_by_type']['STOCK'] else "NINGUNA"}
→ Sectores cubiertos: {', '.join(analysis['stock_sectors']) if analysis['stock_sectors'] else "ninguno"}
→ Sectores FALTANTES: {', '.join(analysis['stock_gaps'][:5]) if analysis['stock_gaps'] else "bien diversificado"}

🚫 **YA EN MI UNIVERSO (NO REPETIR):**
{', '.join(current_tickers) if current_tickers else "(vacío)"}

═══════════════════════════════════════════════════════════════
🎯 TU MISIÓN
═══════════════════════════════════════════════════════════════

Recomienda EXACTAMENTE {MAX_NEW_ASSETS} instrumentos con esta distribución OBLIGATORIA:

🏢 **{num_fibras} FIBRAs mexicanas (GBM):**
   - Busca sectores AUSENTES listados arriba
   - Preferencia: yields >6%, alta liquidez (BMV)
   - Ejemplos específicos por sector:
     * Hotelería: FIHO12 (Marriott/Hilton)
     * Retail: FSHOP13 (centros comerciales)
     * Industrial: TERRA13, FIBRAMQ12 (nearshoring)
     * Infraestructura: FMTY14 (si no está)

📊 **{num_etfs} ETFs internacionales (Bitso):**
   - DIVERSIFICA categorías faltantes listadas arriba
   - Mix de: dividendos, geografía, factores
   - Ejemplos específicos:
     * Dividendos USA: SCHD, VYM (si no tengo dividendos)
     * Emergentes: VWO, EEM (si no tengo emergentes)
     * Internacional: VXUS, VYMI (si solo tengo USA)
     * Small-cap: VB, IJR (si solo tengo large-cap)
     * REITs: VNQ (si no tengo real estate USA)

💼 **{num_stocks} Acciones individuales (Bitso):**
   - Sectores AUSENTES listados arriba
   - Mega-caps líquidas con fundamentos sólidos
   - Ejemplos específicos por sector:
     * Salud: UNH (seguros), JNJ (farmacéutica), LLY (biotech)
     * Finanzas: JPM (banca), V (pagos), BLK (asset mgmt)
     * Consumo: PG (productos hogar), KO (bebidas), WMT (retail)
     * Energía: XOM (oil & gas), NEE (utilities renovables)
     * Industriales: CAT (maquinaria), UPS (logística)

═══════════════════════════════════════════════════════════════
📋 CRITERIOS DE SELECCIÓN (MUY IMPORTANTE)
═══════════════════════════════════════════════════════════════

1. **DIVERSIFICACIÓN REAL:**
   - Llena VACÍOS específicos del portafolio
   - Busca correlaciones BAJAS con holdings actuales
   - Prioriza sectores defensivos/cíclicos que faltan

2. **CALIDAD FUNDAMENTAL (verificable):**
   - FIBRAs: Ocupación >90%, deuda/equity <50%, yield >6%
   - ETFs: AUM >$1B, expense ratio <0.5%, track record >5 años
   - Acciones: Market cap >$50B, P/E <30, deuda manejable, FCF positivo

3. **DIVIDENDOS vs CRECIMIENTO (60/40):**
   - 60% DEBEN pagar dividendos (yield >2%)
   - 40% pueden ser crecimiento puro
   - En "reason", especifica SIEMPRE: "Yield X%" o "Alto crecimiento"

4. **LIQUIDEZ MÍNIMA:**
   - FIBRAs: Volumen >50K títulos/día
   - ETFs: AUM >$500M
   - Acciones: Market cap >$50B, volumen >500K shares/día

5. **TICKER VERIFICABLE:**
   - FIBRAs: TICKER.MX (ej: FIHO12.MX)
   - Internacionales: TICKER (ej: SCHD, UNH)
   - TODOS deben existir en Yahoo Finance

═══════════════════════════════════════════════════════════════
✅ FORMATO JSON (RESPONDE SOLO ESTO)
═══════════════════════════════════════════════════════════════

[
  {{
    "ticker": "FIHO12",
    "yahoo": "FIHO12.MX",
    "broker": "GBM",
    "type": "FIBRA",
    "reason": "Hotelería/turismo - Yield 7.2% - Sector ausente, ingresos dolarizados"
  }},
  {{
    "ticker": "SCHD",
    "yahoo": "SCHD",
    "broker": "Bitso",
    "type": "ETF",
    "reason": "Dividend Growth - Yield 3.5% - Añade dividendos de calidad USA"
  }},
  {{
    "ticker": "UNH",
    "yahoo": "UNH",
    "broker": "Bitso",
    "type": "STOCK",
    "reason": "Salud (seguros) - Yield 1.4% - Sector defensivo ausente, líder"
  }}
]

REGLAS FINALES:
- Responde SOLO el array JSON
- Sin ```json, sin markdown, sin texto adicional
- Máximo 100 caracteres por "reason"
- TODOS deben llenar vacíos reales del portafolio
"""

    try:
        client = OpenAI()
        
        print(f"🎯 Solicitando: {num_fibras} FIBRAs + {num_etfs} ETFs + {num_stocks} acciones = {MAX_NEW_ASSETS} total")
        print(f"\n📊 Vacíos detectados:")
        print(f"   FIBRAs: {', '.join(analysis['fibra_gaps'][:3])}")
        print(f"   ETFs: {', '.join(analysis['etf_gaps'][:3])}")
        print(f"   Stocks: {', '.join(analysis['stock_gaps'][:3])}\n")
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Eres un asesor financiero experto en diversificación de portafolios. Respondes SOLO JSON válido sin markdown."
                },
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=2000,
            temperature=0.4  # Reducido para más consistencia
        )
        
        content = response.choices[0].message.content.strip()
        
        # Limpiar respuesta
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        print(f"\n📥 Respuesta de IA:\n{content}\n")
        
        recommendations = json.loads(content)
        
        if not isinstance(recommendations, list):
            print("❌ Respuesta no es una lista")
            send_discord("⚠️ Error: IA no devolvió lista válida")
            return
        
        # Validar distribución
        count_by_type = {"FIBRA": 0, "ETF": 0, "STOCK": 0}
        for rec in recommendations:
            tipo = rec.get("type", "STOCK")
            count_by_type[tipo] = count_by_type.get(tipo, 0) + 1
        
        print(f"\n📊 Distribución recibida:")
        print(f"   FIBRAs: {count_by_type.get('FIBRA', 0)}/{num_fibras}")
        print(f"   ETFs:   {count_by_type.get('ETF', 0)}/{num_etfs}")
        print(f"   Stocks: {count_by_type.get('STOCK', 0)}/{num_stocks}")
        
        # Validar en Yahoo Finance
        print(f"\n🔍 Validando {len(recommendations)} instrumentos...\n")
        
        valid = []
        valid_by_type = {"FIBRA": [], "ETF": [], "STOCK": []}
        
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            
            ticker = rec.get("ticker")
            yahoo = rec.get("yahoo")
            tipo = rec.get("type", "STOCK")
            
            if not ticker or not yahoo:
                print(f"⏭️  Registro sin ticker/yahoo: {rec}")
                continue
            
            if ticker in current_tickers:
                print(f"⏭️  {ticker} - Ya en universo")
                continue
            
            print(f"⏳ Validando {ticker} ({tipo})...")
            
            if validate_ticker(yahoo):
                valid.append(rec)
                valid_by_type[tipo].append(rec)
                print(f"✅ {ticker} - Válido")
            else:
                print(f"❌ {ticker} - No encontrado en Yahoo Finance")
        
        if not valid:
            msg = "⚠️ **No se encontraron instrumentos nuevos válidos**"
            send_discord(msg)
            print(msg)
            return
        
        # Guardar sugerencias en metadata
        meta = {
            "last_discover": datetime.now().isoformat(),
            "assets_suggested": len(recommendations),
            "assets_valid": len(valid),
            "distribution": {
                "fibras": len(valid_by_type["FIBRA"]),
                "etfs": len(valid_by_type["ETF"]),
                "stocks": len(valid_by_type["STOCK"])
            },
            "pending_suggestions": valid,
            "portfolio_gaps": {
                "fibra_gaps": analysis['fibra_gaps'],
                "etf_gaps": analysis['etf_gaps'],
                "stock_gaps": analysis['stock_gaps']
            }
        }
        save_json(DATA_DISCOVER_META, meta)
        print("✅ Metadata guardada con sugerencias")
        
        # Modo: suggest o commit (resto del código igual)
        if MODE == "suggest":
            msg = "🔍 **SUGERENCIAS DE NUEVOS INSTRUMENTOS**\n\n"
            msg += f"He encontrado **{len(valid)}** instrumentos que complementarían tu portafolio:\n\n"
            
            # Agrupar por tipo
            if valid_by_type["FIBRA"]:
                msg += f"🏢 **FIBRAs Mexicanas ({len(valid_by_type['FIBRA'])}):**\n"
                for v in valid_by_type["FIBRA"]:
                    msg += f"• **{v['ticker']}** - {v['reason']}\n"
                msg += "\n"
            
            if valid_by_type["ETF"]:
                msg += f"📊 **ETFs Internacionales ({len(valid_by_type['ETF'])}):**\n"
                for v in valid_by_type["ETF"]:
                    msg += f"• **{v['ticker']}** - {v['reason']}\n"
                msg += "\n"
            
            if valid_by_type["STOCK"]:
                msg += f"💼 **Acciones Individuales ({len(valid_by_type['STOCK'])}):**\n"
                for v in valid_by_type["STOCK"]:
                    msg += f"• **{v['ticker']}** - {v['reason']}\n"
                msg += "\n"
            
            msg += "📋 **Para agregar estos instrumentos:**\n"
            msg += "1. Bot de Discord: `!discover_commit`\n"
            msg += "2. GitHub Actions: Mode 'commit'\n"
            
            send_discord(msg)
            print(f"\n✅ Sugerencias enviadas ({len(valid)} instrumentos)")
        
        elif MODE == "commit":
            # Leer metadata para obtener sugerencias pendientes
            meta = load_json(DATA_DISCOVER_META)
            pending = meta.get("pending_suggestions", [])
            
            if not pending:
                msg = "⚠️ **No hay sugerencias pendientes**\n\nEjecuta primero en modo 'suggest'"
                send_discord(msg)
                print(msg)
                return
            
            # Agregar al universe
            universe.extend(pending)
            save_json(DATA_UNIVERSE, universe)
            
            msg = f"✅ **{len(pending)} NUEVOS INSTRUMENTOS AGREGADOS**\n\n"
            
            # Agrupar por tipo
            by_type = {"FIBRA": [], "ETF": [], "STOCK": []}
            for v in pending:
                tipo = v.get("type", "STOCK")
                by_type[tipo].append(v)
            
            if by_type["FIBRA"]:
                msg += f"🏢 **FIBRAs ({len(by_type['FIBRA'])}):**\n"
                for v in by_type["FIBRA"]:
                    msg += f"• **{v['ticker']}** - {v['reason']}\n"
                msg += "\n"
            
            if by_type["ETF"]:
                msg += f"📊 **ETFs ({len(by_type['ETF'])}):**\n"
                for v in by_type["ETF"]:
                    msg += f"• **{v['ticker']}** - {v['reason']}\n"
                msg += "\n"
            
            if by_type["STOCK"]:
                msg += f"💼 **Acciones ({len(by_type['STOCK'])}):**\n"
                for v in by_type["STOCK"]:
                    msg += f"• **{v['ticker']}** - {v['reason']}\n"
                msg += "\n"
            
            msg += f"📊 **Universo actualizado:** {len(universe)} instrumentos totales"
            
            send_discord(msg)
            print(f"\n✅ Commiteados {len(pending)} instrumentos")
            
            # Limpiar sugerencias pendientes
            meta["pending_suggestions"] = []
            save_json(DATA_DISCOVER_META, meta)
        
        else:
            print(f"⚠️  MODE desconocido: {MODE}")
    
    except json.JSONDecodeError as e:
        error_msg = f"❌ **Error parseando JSON**\n\n{str(e)}"
        send_discord(error_msg)
        print(error_msg)
    
    except Exception as e:
        error_msg = f"❌ **Error inesperado:** {str(e)}"
        send_discord(error_msg)
        print(error_msg)
        import traceback
        print(traceback.format_exc())


if __name__ == "__main__":
    print(f"🔍 Discover mode: {MODE}")
    print(f"📊 Max nuevos instrumentos: {MAX_NEW_ASSETS}\n")
    discover_new_assets()