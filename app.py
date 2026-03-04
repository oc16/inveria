# app.py
import math
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from analysis_inversio import (
    InvestmentInput,
    analyze_investment,
    scenario_grid,
)

st.set_page_config(page_title="Dashboard inversió immobiliària", layout="wide")

# -----------------------------
# Helpers
# -----------------------------
def euro(x: float) -> str:
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

def pct(x: float) -> str:
    return f"{x:,.2f} %".replace(",", "X").replace(".", ",").replace("X", ".")

def amortization_schedule(principal: float, annual_rate_pct: float, term_years: int) -> pd.DataFrame:
    """
    Amortització francesa: quota constant, desglossant interessos + capital.
    Retorna DF mensual amb saldo.
    """
    n = int(term_years) * 12
    if n <= 0:
        return pd.DataFrame()

    r = (annual_rate_pct / 100.0) / 12.0
    if principal <= 0:
        return pd.DataFrame()

    # Quota
    if abs(r) < 1e-12:
        payment = principal / n
    else:
        pow_ = (1.0 + r) ** n
        payment = principal * r * pow_ / (pow_ - 1.0)

    balance = principal
    rows = []
    for m in range(1, n + 1):
        interest = balance * r
        principal_paid = payment - interest
        balance = max(0.0, balance - principal_paid)

        rows.append({
            "Mes": m,
            "Quota_€": payment,
            "Interessos_€": interest,
            "Capital_€": principal_paid,
            "Saldo_€": balance,
            "Interessos_acum_€": None,  # ho omplim després
            "Capital_acum_€": None,
        })

    df = pd.DataFrame(rows)
    df["Interessos_acum_€"] = df["Interessos_€"].cumsum()
    df["Capital_acum_€"] = df["Capital_€"].cumsum()
    df["Any"] = ((df["Mes"] - 1) // 12) + 1
    return df
    
def kpi_gauge(title: str, value: float, suffix: str, vmin: float, vmax: float, steps, height: int = 240):
    """
    steps = [(a,b,color), ...] on a..b dins [vmin,vmax]
    """
    # value pot ser inf
    if value is None or (isinstance(value, float) and math.isnan(value)):
        value = vmin
    if value == float("inf"):
        # Mostrem al màxim però imprimim "∞" al número
        display_value = vmax
        number = {"valueformat": "", "suffix": suffix, "font": {"size": 34}}
        show_infty = True
    else:
        display_value = max(vmin, min(float(value), vmax))
        number = {"suffix": suffix, "font": {"size": 34}}
        show_infty = False

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=display_value,
        number=number,
        title={"text": title, "font": {"size": 18}},
        gauge={
            "axis": {"range": [vmin, vmax]},
            "bar": {"color": "black"},
            "steps": [{"range": [a, b], "color": c} for (a, b, c) in steps],
            "threshold": {"line": {"color": "black", "width": 4}, "thickness": 0.8, "value": display_value},
        }
    ))
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=height)

    # Truc per mostrar ∞ en text sense duplicar KPI en metric
    if show_infty:
        st.plotly_chart(fig, use_container_width=True)
        st.caption("∞ (sense deute / denominador ~0)")
    else:
        st.plotly_chart(fig, use_container_width=True)
def safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        x = float(x)
        if math.isnan(x):
            return default
        return x
    except Exception:
        return default

def dynamic_paybacks(
    initial_investment: float,
    base_annual_cashflow: float,
    rent_growth_pct: float,
    purchase_price: float,
    appreciation_pct: float,
    amort_df: pd.DataFrame,
    max_years: int = 40,
):
    """
    Retorna (payback_years, equity_payback_years).
    - Payback: acumulat de cashflow
    - Equity Payback: acumulat de cashflow + equity (amortització capital + revalorització)
    Nota: cashflow creix a un ritme constant = rent_growth_pct (aprox).
    """
    inv0 = safe_float(initial_investment, 0.0)
    if inv0 <= 0:
        return 0.0, 0.0

    g_rent = safe_float(rent_growth_pct, 0.0) / 100.0
    g_app = safe_float(appreciation_pct, 0.0) / 100.0
    base_cf = safe_float(base_annual_cashflow, 0.0)

    # Amortització anual real del principal (de la taula)
    principal_by_year = {}
    if amort_df is not None and not amort_df.empty:
        tmp = amort_df.groupby("Any", as_index=True)["Capital_€"].sum()
        principal_by_year = tmp.to_dict()

    cash_acc = 0.0
    equity_acc = 0.0
    payback = float("inf")
    eq_payback = float("inf")

    for year in range(1, max_years + 1):
        # Cashflow anual projectat (aprox creixement lloguer)
        cf_y = base_cf * ((1.0 + g_rent) ** (year - 1))

        # Amortització de capital aquell any (si s’acaba la hipoteca, serà 0)
        principal_y = float(principal_by_year.get(year, 0.0))

        # Revalorització de l'actiu aquell any (aprox sobre el preu de compra)
        # Si vols més realista: purchase_price * ((1+g_app)**(year-1)) * g_app
        appr_y = purchase_price * g_app

        cash_acc += cf_y
        equity_acc += cf_y + principal_y + appr_y

        if payback == float("inf") and cash_acc >= inv0:
            payback = float(year)

        if eq_payback == float("inf") and equity_acc >= inv0:
            eq_payback = float(year)

        if payback != float("inf") and eq_payback != float("inf"):
            break

    return payback, eq_payback

# -----------------------------
# Sidebar inputs
# -----------------------------
st.sidebar.title("Inputs")

purchase_price = st.sidebar.number_input("Preu de compra (€)", min_value=0.0, value=130000.0, step=5000.0)
monthly_rent = st.sidebar.number_input("Lloguer mensual (€)", min_value=0.0, value=650.0, step=25.0)

down_payment_pct = st.sidebar.slider("Entrada (%)", min_value=0.0, max_value=60.0, value=20.0, step=1.0)
term_years = st.sidebar.slider("Termini hipoteca (anys)", min_value=5, max_value=35, value=30, step=1)

interest_type = st.sidebar.selectbox("Tipus d'interès", options=["fixe", "variable"], index=0)
annual_interest_rate = st.sidebar.number_input("Interès anual TIN (%)", min_value=0.0, value=3.2, step=0.1)

monthly_fixed_expenses = st.sidebar.number_input(
    "Despeses fixes mensuals (€) (IBI, comunitat, assegurança, manteniment...)",
    min_value=0.0, value=50.0, step=10.0
)

vacancy_pct = st.sidebar.slider("Vacància (%)", min_value=0.0, max_value=30.0, value=8.0, step=0.5)
default_pct = st.sidebar.slider("Impagament (%)", min_value=0.0, max_value=20.0, value=8.0, step=0.5)

annual_appreciation_pct = st.sidebar.number_input("Revalorització anual (%) (opcional)", min_value=0.0, value=2.0, step=0.5)
annual_rent_growth_pct = st.sidebar.number_input("Creixement anual lloguer (%) (opcional)", min_value=0.0, value=2.0, step=0.5)

st.sidebar.divider()
st.sidebar.subheader("Escenaris")

sc_down = st.sidebar.multiselect("Entrades (%)", [10, 15, 20, 25, 30, 35, 40], default=[10, 20, 30, 40])
sc_terms = st.sidebar.multiselect("Terminis (anys)", [10, 15, 20, 25, 30, 35], default=[20, 25, 30])
sc_shocks = st.sidebar.multiselect("Shocks TIN (punts %)", [0.0, 0.5, 1.0, 2.0], default=[0.0, 1.0, 2.0])

# -----------------------------
# Compute base
# -----------------------------
inp = InvestmentInput(
    purchase_price=purchase_price,
    monthly_rent=monthly_rent,
    down_payment_pct=down_payment_pct,
    term_years=int(term_years),
    annual_interest_rate=annual_interest_rate,
    interest_type=interest_type,
    monthly_fixed_expenses=monthly_fixed_expenses,
    vacancy_pct=vacancy_pct,
    default_pct=default_pct,
    annual_appreciation_pct=annual_appreciation_pct,
    annual_rent_growth_pct=annual_rent_growth_pct,
)

comp = analyze_investment(inp)

# Loan amount (mateixa lògica del teu script: es finança només el preu - entrada)
down_payment_amount = purchase_price * (down_payment_pct / 100.0)
loan_amount = max(0.0, purchase_price - down_payment_amount)

# -----------------------------
# Layout
# -----------------------------
st.title("Dashboard d'inversió immobiliària (lloguer)")

# 1a fila: 4 KPIs + Gauge DSCR (sense repetir DSCR en metric)
k1, k2, k3, k4 = st.columns([1, 1, 1, 1])

k1.metric("Quota hipoteca / mes", euro(comp.monthly_mortgage_payment))
k2.metric("Cashflow / mes", euro(comp.monthly_cashflow))
k3.metric("Cashflow / any", euro(comp.annual_cashflow))
k4.metric("Cash-on-cash", pct(comp.cash_on_cash_pct))

# 2a fila: resta de KPIs
c6, c7, c8, c9, c10 = st.columns(5)
c6.metric("LTV", pct(comp.ltv * 100.0))
c7.metric("Rend. bruta", pct(comp.gross_yield_pct))
c8.metric("Rend. neta (NOI)", pct(comp.net_yield_pct))
c9.metric("Punt mort lloguer / mes", euro(comp.breakeven_monthly_rent))
c10.metric("Risc", comp.risk_level)

# --- Càlculs base ---
# Cash-on-cash ja el tens a comp.cash_on_cash_pct (percent)
coc = comp.cash_on_cash_pct  # %

# DSCR ja el tens a comp.dscr
dscr = comp.dscr

# Payback (anys) = capital inicial / cashflow anual
if comp.annual_cashflow > 0:
    payback_years = down_payment_amount / comp.annual_cashflow
else:
    payback_years = float("inf")

# Equity Payback (anys) = capital inicial / (cashflow + equity gained anual)
# equity gained anual ≈ capital amortitzat (1r any) + revalorització (1r any)
df_am = amortization_schedule(loan_amount, annual_interest_rate, int(term_years))
principal_paid_year1 = float(df_am[df_am["Mes"] <= 12]["Capital_€"].sum()) if not df_am.empty else 0.0
appreciation_year1 = purchase_price * (annual_appreciation_pct / 100.0)

annual_equity_gain = principal_paid_year1 + appreciation_year1
equity_cashflow = comp.annual_cashflow + annual_equity_gain

if equity_cashflow > 0:
    equity_payback_years = down_payment_amount / equity_cashflow
else:
    equity_payback_years = float("inf")


# --- Layout: 4 gauges en una fila ---
g1, g2, g3, g4 = st.columns(4)

with g1:
    # CoC: vermell <3%, groc 3-8%, verd >8% (ajusta al teu criteri)
    kpi_gauge(
        "Cash-on-Cash",
        coc,
        suffix="%",
        vmin=0,
        vmax=20,
        steps=[
            (0, 3,  "#e74c3c"),
            (3, 8,  "#f1c40f"),
            (8, 20, "#2ecc71"),
        ],
    )

with g2:
    # DSCR: vermell <1.0, groc 1.0-1.25, verd >1.25
    # Rang fins 2.5 per visual
    kpi_gauge(
        "DSCR",
        dscr if dscr != float("inf") else float("inf"),
        suffix="x",
        vmin=0,
        vmax=2.5,
        steps=[
            (0.0, 1.0,  "#e74c3c"),
            (1.0, 1.25, "#f1c40f"),
            (1.25, 2.5, "#2ecc71"),
        ],
    )

with g3:
    # Payback: com més petit millor → verd <10a, groc 10-20a, vermell >20a
    kpi_gauge(
        "Payback",
        payback_years,
        suffix="a",
        vmin=0,
        vmax=30,
        steps=[
            (0, 10,  "#2ecc71"),
            (10, 20, "#f1c40f"),
            (20, 30, "#e74c3c"),
        ],
    )

with g4:
    # Equity Payback: també com més petit millor, sovint surt millor que Payback
    kpi_gauge(
        "Equity Payback",
        equity_payback_years,
        suffix="a",
        vmin=0,
        vmax=30,
        steps=[
            (0, 8,   "#2ecc71"),
            (8, 15,  "#f1c40f"),
            (15, 30, "#e74c3c"),
        ],
    )

st.caption(comp.conclusion)

# Tabs
tab1, tab2, tab3 = st.tabs(["Amortització", "Ingressos/Despeses", "Escenaris"])

with tab1:
    st.subheader("Amortització de la hipoteca")

    df_am = amortization_schedule(loan_amount, annual_interest_rate, int(term_years))
    if df_am.empty:
        st.info("No hi ha hipoteca (principal 0 o termini 0).")
    else:
        # Resum anual per fer-ho llegible
        df_year = df_am.groupby("Any", as_index=False).agg({
            "Quota_€": "sum",
            "Interessos_€": "sum",
            "Capital_€": "sum",
            "Saldo_€": "min",
        })

        fig_bal = px.line(df_am, x="Mes", y="Saldo_€", title="Saldo pendent (mensual)")
        st.plotly_chart(fig_bal, use_container_width=True)

        fig_split = px.area(
            df_year,
            x="Any",
            y=["Interessos_€", "Capital_€"],
            title="Composició de la quota (agregat anual)",
        )
        st.plotly_chart(fig_split, use_container_width=True)

        st.dataframe(
            df_year.style.format({
                "Quota_€": euro,
                "Interessos_€": euro,
                "Capital_€": euro,
                "Saldo_€": euro,
            }),
            use_container_width=True,
            height=350
        )

        with st.expander("Veure amortització mensual (taula completa)"):
            st.dataframe(
                df_am.style.format({
                    "Quota_€": euro,
                    "Interessos_€": euro,
                    "Capital_€": euro,
                    "Saldo_€": euro,
                    "Interessos_acum_€": euro,
                    "Capital_acum_€": euro,
                }),
                use_container_width=True,
                height=400
            )

with tab2:
    st.subheader("Ingressos i despeses (anual)")

    # Muntatge simple de components anuals
    df = pd.DataFrame([
        {"Categoria": "Ingressos bruts", "€ / any": comp.gross_annual_rent},
        {"Categoria": "Ingressos nets (vacància + impagament)", "€ / any": comp.net_annual_rent_after_vacancy_default},
        {"Categoria": "Despeses operatives", "€ / any": -comp.annual_operating_expenses},
        {"Categoria": "NOI", "€ / any": comp.noi},
        {"Categoria": "Servei del deute (hipoteca)", "€ / any": -comp.annual_debt_service},
        {"Categoria": "Cashflow", "€ / any": comp.annual_cashflow},
    ])

    fig = px.bar(df, x="Categoria", y="€ / any", title="P&L anual (simplificat)")
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(df.style.format({"€ / any": euro}), use_container_width=True)

    st.subheader("Explicació de risc")
    for bullet in comp.risk_explanation:
        st.write(f"- {bullet}")

with tab3:
    st.subheader("Taula d'escenaris (entrada × anys × shock TIN)")

    rows = scenario_grid(
        base_inp=inp,
        down_pcts=[float(x) for x in sc_down],
        terms=[int(x) for x in sc_terms],
        rate_shocks=[float(x) for x in sc_shocks],
    )
    df_sc = pd.DataFrame(rows)
    if df_sc.empty:
        st.info("Selecciona valors d'escenaris al lateral.")
    else:
        df_sc = df_sc.sort_values(by=["Entrada_%", "Anys", "TIN_%"])
        st.dataframe(df_sc, use_container_width=True, height=420)

        # Heatmap: CoC_% per (Entrada, Anys) a shock 0.0 (o el primer seleccionat)
        shock_for_map = float(sc_shocks[0]) if len(sc_shocks) else 0.0
        df_map = df_sc[df_sc["TIN_%"] == round(annual_interest_rate + shock_for_map, 2)].copy()

        if not df_map.empty:
            pivot = df_map.pivot(index="Entrada_%", columns="Anys", values="CoC_%")
            fig_hm = px.imshow(
                pivot,
                aspect="auto",
                title=f"Heatmap CoC_% (TIN base + {shock_for_map}pp)",
                labels=dict(x="Anys", y="Entrada_%", color="CoC_%"),
            )
            st.plotly_chart(fig_hm, use_container_width=True)
        else:

            st.info("No s'ha pogut generar el heatmap amb el filtre actual de TIN.")




