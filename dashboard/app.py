"""
CallRoute ML — Streamlit Dashboard
Отображает: статистику предиктов, расход кредитов, HITL-очередь, лояльность.
"""
import os
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from datetime import datetime

API_BASE = os.environ.get("API_BASE_URL", "http://api:8000/api/v1")

st.set_page_config(
    page_title="CallRoute ML Dashboard",
    page_icon="📞",
    layout="wide",
)

# ── Auth helpers ──────────────────────────────────────────────────────────────

def login(email: str, password: str) -> str | None:
    try:
        r = requests.post(
            f"{API_BASE}/auth/login",
            data={"username": email, "password": password},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()["access_token"]
    except Exception:
        pass
    return None


def api_get(path: str, token: str) -> dict | list | None:
    try:
        r = requests.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ── Session state ─────────────────────────────────────────────────────────────

if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None

# ── Login form ────────────────────────────────────────────────────────────────

if not st.session_state.token:
    st.title("CallRoute ML — Вход")
    col1, col2 = st.columns([1, 2])
    with col1:
        email = st.text_input("Email")
        password = st.text_input("Пароль", type="password")
        if st.button("Войти", use_container_width=True):
            token = login(email, password)
            if token:
                st.session_state.token = token
                st.session_state.user = api_get("/auth/me", token)
                st.rerun()
            else:
                st.error("Неверный email или пароль")
    st.stop()

token = st.session_state.token
user = st.session_state.user or {}

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📞 CallRoute ML")
    st.markdown(f"**{user.get('email', '')}**")
    st.markdown(f"Уровень: `{user.get('loyalty_level', 'bronze').upper()}`")
    if st.button("Выйти"):
        st.session_state.token = None
        st.session_state.user = None
        st.rerun()

    page = st.radio(
        "Раздел",
        ["Обзор", "Предикты", "Биллинг", "HITL — Разметка", "Тарифы"],
    )

# ── Page: Overview ────────────────────────────────────────────────────────────

if page == "Обзор":
    st.title("Обзор")

    balance_data = api_get("/billing/balance", token) or {}
    loyalty_data = api_get("/billing/loyalty", token) or {}

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Купленные кредиты", f"{balance_data.get('bought_credits', 0):.2f}")
    col2.metric("Бонусные кредиты", f"{balance_data.get('bonus_credits', 0):.2f}")
    col3.metric("Итого кредитов", f"{balance_data.get('total_credits', 0):.2f}")
    col4.metric("Скидка", f"{balance_data.get('discount_pct', 0):.0f}%")

    st.divider()

    # Прогресс до следующего уровня
    st.subheader("Программа лояльности")
    lc1, lc2 = st.columns(2)
    with lc1:
        current_level = loyalty_data.get("current_level", "bronze")
        preds_month = loyalty_data.get("predictions_this_month", 0)
        next_level = loyalty_data.get("next_level")
        to_next = loyalty_data.get("predictions_to_next_level")

        level_colors = {"bronze": "🥉", "silver": "🥈", "gold": "🥇"}
        st.markdown(f"### {level_colors.get(current_level, '')} {current_level.capitalize()}")
        st.markdown(f"Предиктов за месяц: **{preds_month}**")
        if next_level and to_next is not None:
            st.markdown(f"До уровня **{next_level}**: ещё **{to_next}** предиктов")
        else:
            st.success("Максимальный уровень достигнут!")

    with lc2:
        st.markdown(f"Кэшбэк: **{loyalty_data.get('cashback_pct', 0):.0f}%** от расходов за неделю")
        st.markdown(f"Скидка на предикты: **{loyalty_data.get('discount_pct', 0):.0f}%**")

    # Последние предикты
    st.subheader("Последние предикты")
    preds = api_get("/predict?size=5", token) or {}
    items = preds.get("items", [])
    if items:
        df = pd.DataFrame(items)[["task_id", "predicted_intent", "confidence_score", "credits_charged", "status", "created_at"]]
        df.columns = ["ID задачи", "Интент", "Уверенность", "Кредитов", "Статус", "Создано"]
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Предиктов пока нет")

# ── Page: Predictions ─────────────────────────────────────────────────────────

elif page == "Предикты":
    st.title("Предикты")

    # Форма нового предикта
    st.subheader("Новый предикт")
    tiers_data = api_get("/billing/tiers", token) or []
    tier_names = [t["name"] for t in tiers_data]
    tier_desc = {t["name"]: f"{t['name']} — {t['base_cost']} кред. ({t['description']})" for t in tiers_data}

    with st.form("predict_form"):
        text_input = st.text_area("Текст обращения", placeholder="Введите текст звонка или обращения...")
        selected_tier = st.selectbox("Тариф", tier_names, format_func=lambda x: tier_desc.get(x, x))
        submitted = st.form_submit_button("Отправить на классификацию")

    if submitted and text_input.strip():
        try:
            r = requests.post(
                f"{API_BASE}/predict",
                params={"text": text_input, "tier": selected_tier},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if r.status_code in (200, 202):
                data = r.json()
                st.success(f"Задача создана: `{data['task_id']}` | Статус: {data['status']}")
                st.json(data)
            else:
                st.error(f"Ошибка: {r.status_code} — {r.json().get('detail', '')}")
        except Exception as e:
            st.error(f"Ошибка соединения: {e}")

    st.divider()

    # История предиктов
    st.subheader("История предиктов")
    status_filter = st.selectbox("Фильтр по статусу", ["все", "pending", "processing", "completed", "failed"])
    filter_param = "" if status_filter == "все" else f"&status_filter={status_filter}"
    preds = api_get(f"/predict?size=50{filter_param}", token) or {}
    items = preds.get("items", [])

    if items:
        df = pd.DataFrame(items)
        st.markdown(f"Всего: **{preds.get('total', 0)}** задач")

        # Диаграмма по интентам
        if "predicted_intent" in df.columns:
            intent_counts = df["predicted_intent"].value_counts().reset_index()
            intent_counts.columns = ["intent", "count"]
            fig = px.bar(intent_counts, x="intent", y="count", title="Распределение интентов")
            st.plotly_chart(fig, use_container_width=True)

        display_cols = [c for c in ["task_id", "predicted_intent", "confidence_score", "credits_charged", "status", "created_at"] if c in df.columns]
        st.dataframe(df[display_cols], use_container_width=True)
    else:
        st.info("Нет данных")

# ── Page: Billing ─────────────────────────────────────────────────────────────

elif page == "Биллинг":
    st.title("Биллинг")

    # Пополнение
    st.subheader("Пополнить баланс")
    with st.form("topup_form"):
        amount = st.number_input("Сумма (кредитов)", min_value=1.0, max_value=10000.0, value=100.0, step=10.0)
        topup_submit = st.form_submit_button("Пополнить")

    if topup_submit:
        try:
            r = requests.post(
                f"{API_BASE}/billing/topup",
                params={"amount": amount},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                st.success(f"Баланс пополнен. Купленные: {data['new_bought_balance']:.2f}, Бонусные: {data['new_bonus_balance']:.2f}")
            else:
                st.error(r.json().get("detail", "Ошибка"))
        except Exception as e:
            st.error(str(e))

    st.divider()

    # История транзакций
    st.subheader("История транзакций")
    tx_data = api_get("/billing/transactions?size=100", token) or {}
    items = tx_data.get("items", [])

    if items:
        df = pd.DataFrame(items)
        st.markdown(f"Всего транзакций: **{tx_data.get('total', 0)}**")

        # График по типам транзакций
        type_counts = df["type"].value_counts().reset_index()
        type_counts.columns = ["type", "count"]
        fig = px.pie(type_counts, names="type", values="count", title="Типы транзакций")
        st.plotly_chart(fig, use_container_width=True)

        # Динамика расходов
        df["created_at"] = pd.to_datetime(df["created_at"])
        debits = df[df["type"] == "DEBIT_PREDICTION"].copy()
        if not debits.empty:
            debits["date"] = debits["created_at"].dt.date
            daily = debits.groupby("date")["amount"].sum().reset_index()
            fig2 = px.line(daily, x="date", y="amount", title="Расход кредитов по дням")
            st.plotly_chart(fig2, use_container_width=True)

        display_cols = ["type", "amount", "balance_type", "description", "created_at"]
        st.dataframe(df[display_cols], use_container_width=True)
    else:
        st.info("Транзакций пока нет")

# ── Page: HITL ────────────────────────────────────────────────────────────────

elif page == "HITL — Разметка":
    st.title("HITL — Разметка предиктов")
    st.info("Разметьте обращения с низкой уверенностью модели и получите бонусные кредиты за каждое выполненное задание.")

    tasks = api_get("/billing/hitl/tasks", token) or []

    if not tasks:
        st.success("Нет заданий для разметки. Загляните позже!")
    else:
        st.markdown(f"Доступно заданий: **{len(tasks)}**")

        INTENT_OPTIONS = [
            "return_request", "technical_issue", "payment_issue", "fraud_report",
            "general_inquiry", "complaint", "account_management", "escalation_request",
        ]

        for task in tasks:
            with st.expander(f"Задание {task['id'][:8]}… | Предсказано: {task['model_prediction']} | Уверенность: {task['model_confidence']:.2%} | Награда: {task['reward_credits']} кред."):
                st.markdown(f"**Текст обращения:**")
                st.text_area("", value=task["input_text"], disabled=True, key=f"text_{task['id']}")
                st.markdown(f"Модель предсказала: `{task['model_prediction']}` с уверенностью {task['model_confidence']:.2%}")

                chosen = st.selectbox(
                    "Правильный интент",
                    INTENT_OPTIONS,
                    index=INTENT_OPTIONS.index(task["model_prediction"]) if task["model_prediction"] in INTENT_OPTIONS else 0,
                    key=f"sel_{task['id']}",
                )

                if st.button(f"Подтвердить — получить {task['reward_credits']} кредитов", key=f"btn_{task['id']}"):
                    try:
                        r = requests.post(
                            f"{API_BASE}/billing/hitl/tasks/{task['id']}/complete",
                            params={"correct_label": chosen},
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=10,
                        )
                        if r.status_code == 200:
                            st.success(r.json()["message"])
                            st.rerun()
                        else:
                            st.error(r.json().get("detail", "Ошибка"))
                    except Exception as e:
                        st.error(str(e))

# ── Page: Tiers ───────────────────────────────────────────────────────────────

elif page == "Тарифы":
    st.title("Тарифы предиктов")

    tiers = api_get("/billing/tiers", token) or []

    if tiers:
        cols = st.columns(len(tiers))
        tier_icons = {"fast": "⚡", "smart": "🧠", "batch": "📦"}
        for col, tier in zip(cols, tiers):
            with col:
                icon = tier_icons.get(tier["name"], "")
                st.markdown(f"### {icon} {tier['name'].capitalize()}")
                st.metric("Стоимость", f"{tier['base_cost']} кред.")
                st.markdown(tier.get("description", ""))
                st.markdown(f"Лимит текста: {tier['max_input_chars']} символов")
    else:
        st.error("Не удалось загрузить тарифы")
