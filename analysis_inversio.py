#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
analysis_inversio.py
Eina per analitzar la rendibilitat d'una inversió immobiliària per lloguer.

Funcionalitats:
- Cost total d'adquisició incloent ITP (10%) i notaria/gestió (2,5%)
- Hipoteca amb amortització francesa (quota constant)
- Ingressos nets (vacància + impagament)
- Despeses operatives + hipoteca
- Cashflow mensual/anual
- Rendibilitat bruta i neta
- Cash-on-cash (ROI anual sobre capital invertit)
- DSCR, LTV
- Punt mort (lloguer mínim)
- Escenaris: % entrada x anys hipoteca x interès (base, +1%, +2%)
- Qualificació de risc (baix/mitjà/alt) amb explicació

Execució:
    python analysis_inversio.py

Requeriments:
    - Python 3.9+
    - pandas (opcional però recomanat per mostrar taules millor)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

import math
import sys

# Pandas és opcional: si no està instal·lat, fem taula en text.
try:
    import pandas as pd  # type: ignore
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False


# -----------------------------
# Config / Constants
# -----------------------------

ITP_RATE = 0.10
NOTARY_RATE = 0.025

DEFAULT_ENTRY_SCENARIOS = [10, 20, 30, 40]         # %
DEFAULT_TERM_SCENARIOS = [15, 20, 25, 30]          # anys
DEFAULT_RATE_SHOCKS = [0.0, 1.0, 2.0]              # punts percentuals (TIN + shock)


# -----------------------------
# Models de dades
# -----------------------------

@dataclass(frozen=True)
class InvestmentInput:
    purchase_price: float                 # € (valor compra)
    monthly_rent: float                   # € (lloguer mensual esperat)
    down_payment_pct: float               # % (entrada)
    term_years: int                       # anys hipoteca
    annual_interest_rate: float           # % TIN
    interest_type: str                    # "fixe" o "variable"
    monthly_fixed_expenses: float         # € mensuals (IBI prorratejat, comunitat, assegurança, manteniment...)
    vacancy_pct: float                    # % (vacància)
    default_pct: float                    # % (impagament, pot ser 0)
    annual_appreciation_pct: float        # % (opcional, pot ser 0)
    annual_rent_growth_pct: float         # % (opcional, pot ser 0)


@dataclass(frozen=True)
class InvestmentComputed:
    # Costos inicials
    itp_cost: float
    notary_cost: float
    total_acquisition_cost: float
    initial_cash_invested: float

    # Hipoteca
    loan_amount: float
    monthly_mortgage_payment: float
    annual_debt_service: float
    ltv: float

    # Operativa anual
    gross_annual_rent: float
    net_annual_rent_after_vacancy_default: float
    annual_operating_expenses: float
    noi: float  # Net Operating Income (abans de deute)

    # Resultats
    annual_cashflow: float
    monthly_cashflow: float
    gross_yield_pct: float
    net_yield_pct: float
    cash_on_cash_pct: float
    dscr: float

    # Punt mort
    breakeven_monthly_rent: float

    # Risc
    risk_level: str
    risk_explanation: List[str]

    # Conclusió
    is_profitable: bool
    conclusion: str


# -----------------------------
# Validació / Input
# -----------------------------

def _read_float(prompt: str, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
    while True:
        raw = input(prompt).strip().replace(",", ".")
        try:
            val = float(raw)
        except ValueError:
            print("  ✖ Introdueix un número vàlid.")
            continue

        if min_value is not None and val < min_value:
            print(f"  ✖ Ha de ser >= {min_value}.")
            continue
        if max_value is not None and val > max_value:
            print(f"  ✖ Ha de ser <= {max_value}.")
            continue
        return val


def _read_int(prompt: str, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            val = int(raw)
        except ValueError:
            print("  ✖ Introdueix un enter vàlid.")
            continue

        if min_value is not None and val < min_value:
            print(f"  ✖ Ha de ser >= {min_value}.")
            continue
        if max_value is not None and val > max_value:
            print(f"  ✖ Ha de ser <= {max_value}.")
            continue
        return val


def _read_choice(prompt: str, choices: List[str]) -> str:
    choices_lower = [c.lower() for c in choices]
    while True:
        raw = input(prompt).strip().lower()
        if raw in choices_lower:
            return raw
        print(f"  ✖ Opció no vàlida. Tria entre: {', '.join(choices)}")


def gather_user_input() -> InvestmentInput:
    print("\n=== DADES DE L'OPERACIÓ (compra + hipoteca + lloguer) ===")

    purchase_price = _read_float("Valor de compra de l'immoble (€): ", min_value=0.01)
    monthly_rent = _read_float("Lloguer mensual esperat (€): ", min_value=0.0)

    down_payment_pct = _read_float("Percentatge d'entrada (%), ex. 20: ", min_value=0.0, max_value=100.0)
    term_years = _read_int("Anys d'hipoteca (ex. 25): ", min_value=1, max_value=50)

    interest_type = _read_choice("Tipus d'interès (fixe/variable): ", ["fixe", "variable"])
    annual_interest_rate = _read_float("Tipus d'interès anual TIN (%), ex. 3.2: ", min_value=0.0, max_value=100.0)

    monthly_fixed_expenses = _read_float(
        "Despeses mensuals fixes (€) (IBI prorratejat, comunitat, assegurança, manteniment...): ",
        min_value=0.0
    )

    vacancy_pct = _read_float("Vacància estimada (% anual sobre ingressos), ex. 5: ", min_value=0.0, max_value=100.0)

    default_pct = _read_float("Impagament (% anual sobre ingressos) [0 si no vols]: ", min_value=0.0, max_value=100.0)

    annual_appreciation_pct = _read_float("Revalorització anual esperada (%) [0 si no vols]: ", min_value=0.0, max_value=100.0)
    annual_rent_growth_pct = _read_float("Increment anual del lloguer (%) [0 si no vols]: ", min_value=0.0, max_value=100.0)

    return InvestmentInput(
        purchase_price=purchase_price,
        monthly_rent=monthly_rent,
        down_payment_pct=down_payment_pct,
        term_years=term_years,
        annual_interest_rate=annual_interest_rate,
        interest_type=interest_type,
        monthly_fixed_expenses=monthly_fixed_expenses,
        vacancy_pct=vacancy_pct,
        default_pct=default_pct,
        annual_appreciation_pct=annual_appreciation_pct,
        annual_rent_growth_pct=annual_rent_growth_pct
    )


# -----------------------------
# Finances: hipoteca, mètriques
# -----------------------------

def compute_acquisition_costs(purchase_price: float) -> Tuple[float, float, float]:
    """
    Retorna: (itp_cost, notary_cost, total_acquisition_cost)
    total_acquisition_cost = compra + ITP(10%) + notaria/gestió(2,5%)
    """
    itp_cost = purchase_price * ITP_RATE
    notary_cost = purchase_price * NOTARY_RATE
    total = purchase_price + itp_cost + notary_cost
    return itp_cost, notary_cost, total


def monthly_payment_french_amortization(principal: float, annual_rate_pct: float, term_years: int) -> float:
    """
    Quota mensual amb amortització francesa (quota constant).
    Si rate=0, quota = principal / n
    """
    n = term_years * 12
    if n <= 0:
        raise ValueError("term_years ha de ser > 0")

    r = (annual_rate_pct / 100.0) / 12.0
    if principal <= 0:
        return 0.0
    if abs(r) < 1e-12:
        return principal / n

    # P * r * (1+r)^n / ((1+r)^n - 1)
    pow_ = (1.0 + r) ** n
    payment = principal * r * pow_ / (pow_ - 1.0)
    return payment


def compute_effective_income(monthly_rent: float, vacancy_pct: float, default_pct: float) -> Tuple[float, float]:
    """
    Retorna (gross_annual_rent, net_annual_rent_after_vacancy_default)
    Assumeix que vacància i impagament redueixen ingressos de manera multiplicativa
    sobre la renda bruta anual (aproximació conservadora i simple).
    """
    gross = monthly_rent * 12.0
    vacancy_factor = 1.0 - (vacancy_pct / 100.0)
    default_factor = 1.0 - (default_pct / 100.0)
    net = gross * max(0.0, vacancy_factor) * max(0.0, default_factor)
    return gross, net


def compute_breakeven_rent(
    annual_operating_expenses: float,
    annual_debt_service: float,
    vacancy_pct: float,
    default_pct: float
) -> float:
    """
    Lloguer mensual mínim perquè el cashflow anual sigui >= 0.
    cashflow = ingressos_nets - opex - deute >= 0

    ingressos_nets = (rent*12) * (1-v) * (1-d)
    -> rent >= (opex+deute) / (12*(1-v)*(1-d))
    """
    denom = 12.0 * (1.0 - vacancy_pct / 100.0) * (1.0 - default_pct / 100.0)
    if denom <= 0:
        return float("inf")
    return (annual_operating_expenses + annual_debt_service) / denom


# -----------------------------
# Risc i conclusió
# -----------------------------

def risk_assessment(
    monthly_cashflow: float,
    dscr: float,
    ltv: float,
    sensitivity_cashflow_after_shocks: Optional[List[float]] = None
) -> Tuple[str, List[str]]:
    """
    Classificació simple i explicable:
    - DSCR < 1.0: alt (no cobreix deute)
    - Cashflow mensual negatiu: alt (o mínim, si és lleu)
    - LTV > 80%: incrementa risc
    - Sensibilitat: si qualsevol shock dona cashflow negatiu -> puja risc
    """
    notes: List[str] = []
    score = 0

    # DSCR
    if dscr < 1.0:
        score += 4
        notes.append(f"DSCR {dscr:.2f} < 1.00: el NOI no cobreix el servei del deute.")
    elif dscr < 1.2:
        score += 2
        notes.append(f"DSCR {dscr:.2f} és ajustat (<1.20): poc marge davant imprevistos.")
    else:
        notes.append(f"DSCR {dscr:.2f} és saludable (≥1.20).")

    # Cashflow
    if monthly_cashflow < 0:
        # Diferenciem si és lleu o fort
        if monthly_cashflow > -100:
            score += 2
            notes.append(f"Cashflow mensual negatiu però lleu ({monthly_cashflow:.0f} €/mes).")
        else:
            score += 3
            notes.append(f"Cashflow mensual negatiu ({monthly_cashflow:.0f} €/mes): tensió de liquiditat.")
    elif monthly_cashflow < 100:
        score += 1
        notes.append(f"Cashflow mensual molt just ({monthly_cashflow:.0f} €/mes).")
    else:
        notes.append(f"Cashflow mensual positiu ({monthly_cashflow:.0f} €/mes).")

    # LTV
    if ltv > 0.9:
        score += 3
        notes.append(f"LTV {ltv*100:.0f}% > 90%: alt apalancament, més risc davant baixades de preu o refinançament.")
    elif ltv > 0.8:
        score += 2
        notes.append(f"LTV {ltv*100:.0f}% > 80%: apalancament elevat.")
    elif ltv > 0.7:
        score += 1
        notes.append(f"LTV {ltv*100:.0f}% moderat.")
    else:
        notes.append(f"LTV {ltv*100:.0f}% conservador.")

    # Sensibilitat a shocks
    if sensitivity_cashflow_after_shocks:
        if any(cf < 0 for cf in sensitivity_cashflow_after_shocks):
            score += 2
            notes.append("Sensibilitat: en algun escenari de pujada de tipus, el cashflow passa a negatiu.")
        else:
            notes.append("Sensibilitat: el cashflow aguanta els shocks de tipus considerats.")

    # Determinar nivell
    if score >= 7:
        return "alt", notes
    if score >= 4:
        return "mitjà", notes
    return "baix", notes


def profitability_conclusion(
    annual_cashflow: float,
    cash_on_cash_pct: float,
    dscr: float,
    min_cash_on_cash_pct: float = 5.0
) -> Tuple[bool, str]:
    """
    Criteris simples (explicables):
    - Rendible si:
        - cashflow anual >= 0
        - DSCR >= 1.10 (marge mínim)
        - cash-on-cash >= min_cash_on_cash_pct (per defecte 5%)
    """
    reasons = []
    ok = True

    if annual_cashflow < 0:
        ok = False
        reasons.append(f"cashflow anual negatiu ({annual_cashflow:.0f} €/any)")
    else:
        reasons.append(f"cashflow anual positiu ({annual_cashflow:.0f} €/any)")

    if dscr < 1.10:
        ok = False
        reasons.append(f"DSCR insuficient ({dscr:.2f} < 1.10)")
    else:
        reasons.append(f"DSCR acceptable ({dscr:.2f})")

    if cash_on_cash_pct < min_cash_on_cash_pct:
        ok = False
        reasons.append(f"cash-on-cash baix ({cash_on_cash_pct:.2f}% < {min_cash_on_cash_pct:.0f}%)")
    else:
        reasons.append(f"cash-on-cash correcte ({cash_on_cash_pct:.2f}%)")

    label = "RENDIBLE" if ok else "NO RENDIBLE"
    conclusion = f"{label}: " + "; ".join(reasons) + "."
    return ok, conclusion


# -----------------------------
# Motor principal de càlcul
# -----------------------------

def analyze_investment(inp: InvestmentInput, rate_shock_pct_points: float = 0.0) -> InvestmentComputed:
    """
    Calcula totes les mètriques per una entrada concreta.
    rate_shock_pct_points s'afegeix al TIN (ex: +1.0, +2.0).
    """

    # Costos d'adquisició (obligatoris)
    itp_cost, notary_cost, total_acq = compute_acquisition_costs(inp.purchase_price)

    # Entrada (sobre valor compra, no sobre cost total)
    down_payment_amount = inp.purchase_price * (inp.down_payment_pct / 100.0)

    # Assumpció: impostos i notaria NO es financen (capital inicial)
    initial_cash_invested = down_payment_amount + itp_cost + notary_cost

    # Hipoteca finança la resta del preu de compra (no inclou impostos/despeses)
    loan_amount = max(0.0, inp.purchase_price - down_payment_amount)

    # LTV (loan-to-value) sobre preu de compra
    ltv = 0.0 if inp.purchase_price == 0 else loan_amount / inp.purchase_price

    # Quota mensual
    effective_rate = inp.annual_interest_rate + rate_shock_pct_points
    monthly_payment = monthly_payment_french_amortization(loan_amount, effective_rate, inp.term_years)
    annual_debt_service = monthly_payment * 12.0

    # Ingressos
    gross_annual_rent, net_annual_rent = compute_effective_income(
        monthly_rent=inp.monthly_rent,
        vacancy_pct=inp.vacancy_pct,
        default_pct=inp.default_pct
    )

    # Despeses operatives (anuals)
    annual_operating_expenses = inp.monthly_fixed_expenses * 12.0

    # NOI (abans de deute)
    noi = net_annual_rent - annual_operating_expenses

    # Cashflow (després de deute)
    annual_cashflow = noi - annual_debt_service
    monthly_cashflow = annual_cashflow / 12.0

    # Rendibilitats
    gross_yield_pct = 0.0 if total_acq == 0 else (gross_annual_rent / total_acq) * 100.0
    net_yield_pct = 0.0 if total_acq == 0 else (noi / total_acq) * 100.0

    # Cash-on-cash / ROI anual sobre capital invertit
    cash_on_cash_pct = 0.0 if initial_cash_invested == 0 else (annual_cashflow / initial_cash_invested) * 100.0

    # DSCR = NOI / servei del deute
    dscr = float("inf") if annual_debt_service == 0 else (noi / annual_debt_service)

    # Punt mort
    breakeven_monthly_rent = compute_breakeven_rent(
        annual_operating_expenses=annual_operating_expenses,
        annual_debt_service=annual_debt_service,
        vacancy_pct=inp.vacancy_pct,
        default_pct=inp.default_pct
    )

    # Sensibilitat: si estem analitzant escenari base, podem mirar shocks típics
    # (només ho fem quan shock=0 per no duplicar feina)
    sensitivity_list = None
    if abs(rate_shock_pct_points) < 1e-12:
        sensitivity_list = []
        for s in DEFAULT_RATE_SHOCKS:
            if s == 0.0:
                continue
            mp = monthly_payment_french_amortization(loan_amount, inp.annual_interest_rate + s, inp.term_years)
            ads = mp * 12.0
            cf = noi - ads
            sensitivity_list.append(cf / 12.0)

    risk_level, risk_notes = risk_assessment(
        monthly_cashflow=monthly_cashflow,
        dscr=dscr,
        ltv=ltv,
        sensitivity_cashflow_after_shocks=sensitivity_list
    )

    is_profitable, conclusion = profitability_conclusion(
        annual_cashflow=annual_cashflow,
        cash_on_cash_pct=cash_on_cash_pct,
        dscr=dscr
    )

    return InvestmentComputed(
        itp_cost=itp_cost,
        notary_cost=notary_cost,
        total_acquisition_cost=total_acq,
        initial_cash_invested=initial_cash_invested,
        loan_amount=loan_amount,
        monthly_mortgage_payment=monthly_payment,
        annual_debt_service=annual_debt_service,
        ltv=ltv,
        gross_annual_rent=gross_annual_rent,
        net_annual_rent_after_vacancy_default=net_annual_rent,
        annual_operating_expenses=annual_operating_expenses,
        noi=noi,
        annual_cashflow=annual_cashflow,
        monthly_cashflow=monthly_cashflow,
        gross_yield_pct=gross_yield_pct,
        net_yield_pct=net_yield_pct,
        cash_on_cash_pct=cash_on_cash_pct,
        dscr=dscr,
        breakeven_monthly_rent=breakeven_monthly_rent,
        risk_level=risk_level,
        risk_explanation=risk_notes,
        is_profitable=is_profitable,
        conclusion=conclusion
    )


# -----------------------------
# Escenaris / Taules
# -----------------------------

def scenario_grid(
    base_inp: InvestmentInput,
    down_pcts: List[float],
    terms: List[int],
    rate_shocks: List[float]
) -> List[Dict[str, Any]]:
    """
    Genera una llista de diccionaris per a una taula comparativa d'escenaris.
    """
    rows: List[Dict[str, Any]] = []
    for dp in down_pcts:
        for term in terms:
            for shock in rate_shocks:
                inp = InvestmentInput(
                    purchase_price=base_inp.purchase_price,
                    monthly_rent=base_inp.monthly_rent,
                    down_payment_pct=dp,
                    term_years=term,
                    annual_interest_rate=base_inp.annual_interest_rate,
                    interest_type=base_inp.interest_type,
                    monthly_fixed_expenses=base_inp.monthly_fixed_expenses,
                    vacancy_pct=base_inp.vacancy_pct,
                    default_pct=base_inp.default_pct,
                    annual_appreciation_pct=base_inp.annual_appreciation_pct,
                    annual_rent_growth_pct=base_inp.annual_rent_growth_pct
                )
                comp = analyze_investment(inp, rate_shock_pct_points=shock)
                rows.append({
                    "Entrada_%": dp,
                    "Anys": term,
                    "TIN_%": round(base_inp.annual_interest_rate + shock, 2),
                    "Quota_mes_€": round(comp.monthly_mortgage_payment, 2),
                    "CF_mes_€": round(comp.monthly_cashflow, 2),
                    "CF_any_€": round(comp.annual_cashflow, 2),
                    "CoC_%": round(comp.cash_on_cash_pct, 2),
                    "DSCR": round(comp.dscr, 2) if math.isfinite(comp.dscr) else comp.dscr,
                    "LTV_%": round(comp.ltv * 100.0, 1),
                    "Risc": comp.risk_level,
                })
    return rows


def print_table(rows: List[Dict[str, Any]]) -> None:
    """
    Imprimeix taula (pandas si està disponible, sinó taula text).
    """
    if not rows:
        print("No hi ha escenaris.")
        return

    if HAS_PANDAS:
        df = pd.DataFrame(rows)
        # Ordenar perquè sigui llegible
        df = df.sort_values(by=["Entrada_%", "Anys", "TIN_%"], ascending=[True, True, True])
        # Ajust format a consola
        with pd.option_context("display.max_rows", 500, "display.max_columns", 50, "display.width", 140):
            print(df.to_string(index=False))
        return

    # Fallback: taula en text
    cols = list(rows[0].keys())
    # Amplades
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    sep = " | "
    header = sep.join(c.ljust(widths[c]) for c in cols)
    line = "-+-".join("-" * widths[c] for c in cols)

    print(header)
    print(line)
    for r in rows:
        print(sep.join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


# -----------------------------
# Presentació
# -----------------------------

def money(x: float) -> str:
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x: float, decimals: int = 2) -> str:
    return f"{x:.{decimals}f}%"


def print_summary(inp: InvestmentInput, comp: InvestmentComputed) -> None:
    print("\n" + "=" * 72)
    print("RESUM DE L'ANÀLISI")
    print("=" * 72)

    print("\n--- Costos inicials (obligatoris) ---")
    print(f"Preu compra:                {money(inp.purchase_price)}")
    print(f"ITP (10%):                  {money(comp.itp_cost)}")
    print(f"Notaria/gestió (2,5%):      {money(comp.notary_cost)}")
    print(f"Cost total adquisició:      {money(comp.total_acquisition_cost)}")

    print("\n--- Capital i hipoteca ---")
    down_amount = inp.purchase_price * (inp.down_payment_pct / 100.0)
    print(f"Entrada ({inp.down_payment_pct:.1f}%):           {money(down_amount)}")
    print(f"Capital inicial invertit:   {money(comp.initial_cash_invested)}")
    print("  (Assumpció: impostos i notaria NO es financen i es paguen al comptat)")
    print(f"Import hipoteca:            {money(comp.loan_amount)}")
    print(f"Quota mensual (francesa):   {money(comp.monthly_mortgage_payment)}")
    print(f"LTV:                        {pct(comp.ltv*100, 1)}")

    print("\n--- Ingressos i despeses anuals ---")
    print(f"Ingressos bruts anuals:     {money(comp.gross_annual_rent)}")
    print(f"Ingressos nets (vac+imp):   {money(comp.net_annual_rent_after_vacancy_default)}")
    print(f"Despeses operatives anuals: {money(comp.annual_operating_expenses)}")
    print(f"NOI (abans de deute):       {money(comp.noi)}")
    print(f"Servei del deute anual:     {money(comp.annual_debt_service)}")

    print("\n--- Resultats clau ---")
    print(f"Cashflow mensual:           {money(comp.monthly_cashflow)}")
    print(f"Cashflow anual:             {money(comp.annual_cashflow)}")
    print(f"Rendibilitat bruta:         {pct(comp.gross_yield_pct)} (sobre cost total adquisició)")
    print(f"Rendibilitat neta (NOI):    {pct(comp.net_yield_pct)} (sobre cost total adquisició)")
    print(f"Cash-on-cash (ROI anual):   {pct(comp.cash_on_cash_pct)} (sobre capital invertit)")
    print(f"DSCR:                       {comp.dscr:.2f}")
    print(f"Punt mort (lloguer/mes):    {money(comp.breakeven_monthly_rent)}")

    print("\n--- Risc ---")
    print(f"Nivell de risc:             {comp.risk_level.upper()}")
    for n in comp.risk_explanation:
        print(f"  - {n}")

    print("\n--- Conclusió ---")
    print(comp.conclusion)
    print("=" * 72)


# -----------------------------
# Main
# -----------------------------

def main() -> int:
    inp = gather_user_input()

    # Escenari base (TIN sense shocks)
    base = analyze_investment(inp, rate_shock_pct_points=0.0)
    print_summary(inp, base)

    print("\n\n=== TAULA D'ESCENARIS ===")
    print("Inclou combinacions de: % entrada x anys hipoteca x (TIN base, +1%, +2%)")
    down_pcts = DEFAULT_ENTRY_SCENARIOS
    terms = DEFAULT_TERM_SCENARIOS
    rate_shocks = DEFAULT_RATE_SHOCKS

    rows = scenario_grid(
        base_inp=inp,
        down_pcts=down_pcts,
        terms=terms,
        rate_shocks=rate_shocks
    )
    print_table(rows)

    # Nota extra si interès variable
    if inp.interest_type == "variable":
        print("\nNota (interès variable): la taula ja incorpora sensibilitat a pujades de +1% i +2% sobre el TIN base.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterromput per l'usuari.")
        raise SystemExit(130)
