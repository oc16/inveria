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
    
def dscr_gauge(dscr: float):
    # Llindars típics (ajusta si vols):
    # < 1.00 = vermell (no cobreix deute)
    # 1.00–1.25 = groc (justet)
    # > 1.25 = verd (sa)
    if dscr is None:
        dscr = 0.0

    # Si no hi ha deute, el teu comp.dscr pot ser inf
    if dscr == float("inf"):
        st.success("DSCR: ∞ (sense deute)")
        return

    vmax = 2.5  # escala del gauge
    v = max(0.0, min(float(dscr), vmax))

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=v,
        number={"suffix": "x", "font": {"size": 40}},
        title={"text": "DSCR", "font": {"size": 22}},
        gauge={
            "axis": {"range": [0, vmax]},
            "bar": {"color": "black"},
            "steps": [
                {"range": [0.0, 1.0], "color": "#e74c3c"},    # vermell
                {"range": [1.0, 1.25], "color": "#f1c40f"},   # groc
                {"range": [1.25, vmax], "color": "#2ecc71"},  # verd
            ],
            "threshold": {
                "line": {"color": "black", "width": 4},
                "thickness": 0.8,
                "value": v
            }
        }
    ))

    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=130)
    st.plotly_chart(fig, use_container_width=True)
    
# -----------------------------
# Sidebar inputs
# -----------------------------
st.sidebar.title("Inputs")

purchase_price = st.sidebar.number_input("Preu de compra (€)", min_value=0.0, value=200000.0, step=5000.0)
monthly_rent = st.sidebar.number_input("Lloguer mensual (€)", min_value=0.0, value=1100.0, step=25.0)

down_payment_pct = st.sidebar.slider("Entrada (%)", min_value=0.0, max_value=60.0, value=20.0, step=1.0)
term_years = st.sidebar.slider("Termini hipoteca (anys)", min_value=5, max_value=35, value=25, step=1)
annual_interest_rate = st.sidebar.number_input("Interès anual TIN (%)", min_value=0.0, value=3.2, step=0.1)

interest_type = st.sidebar.selectbox("Tipus d'interès", options=["fixe", "variable"], index=0)

monthly_fixed_expenses = st.sidebar.number_input(
    "Despeses fixes mensuals (€) (IBI, comunitat, assegurança, manteniment...)",
    min_value=0.0, value=180.0, step=10.0
)

vacancy_pct = st.sidebar.slider("Vacància (%)", min_value=0.0, max_value=30.0, value=5.0, step=0.5)
default_pct = st.sidebar.slider("Impagament (%)", min_value=0.0, max_value=20.0, value=0.0, step=0.5)

annual_appreciation_pct = st.sidebar.number_input("Revalorització anual (%) (opcional)", min_value=0.0, value=0.0, step=0.5)
annual_rent_growth_pct = st.sidebar.number_input("Creixement anual lloguer (%) (opcional)", min_value=0.0, value=0.0, step=0.5)

st.sidebar.divider()
st.sidebar.subheader("Escenaris")

sc_down = st.sidebar.multiselect("Entrades (%)", [10, 15, 20, 25, 30, 35, 40], default=[10, 20, 30, 40])
sc_terms = st.sidebar.multiselect("Terminis (anys)", [10, 15, 20, 25, 30, 35], default=[15, 20, 25, 30])
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
k1, k2, k3, k4, g = st.columns([1, 1, 1, 1, 1.2])

k1.metric("Quota hipoteca / mes", euro(comp.monthly_mortgage_payment))
k2.metric("Cashflow / mes", euro(comp.monthly_cashflow))
k3.metric("Cashflow / any", euro(comp.annual_cashflow))
k4.metric("Cash-on-cash", pct(comp.cash_on_cash_pct))

with g:
    dscr_gauge(comp.dscr)  # <-- la teva funció gauge ja declarada

# 2a fila: resta de KPIs
c6, c7, c8, c9, c10 = st.columns(5)
c6.metric("LTV", pct(comp.ltv * 100.0))
c7.metric("Rend. bruta", pct(comp.gross_yield_pct))
c8.metric("Rend. neta (NOI)", pct(comp.net_yield_pct))
c9.metric("Punt mort lloguer / mes", euro(comp.breakeven_monthly_rent))
c10.metric("Risc", comp.risk_level)

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

