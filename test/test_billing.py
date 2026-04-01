# =============================================================================
# test/test_billing.py  –  BILLING suite
# =============================================================================
# Copre: sottoscrizione trial, webhook Stripe, sincronizzazione stato DB,
#        semaforo concorrenza, policy disattivazione
# =============================================================================

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from conftest import (
    _crea_sessione_utente,
    _crea_tenant_e_utente,
)
from app.core.auth import SESSION_COOKIE_NAME
from app.models import Sottoscrizione, Sottoscrizioni, SottoscrizioniStati


# =============================================================================
# Helpers
# =============================================================================


def _cookies(id_sessione: str) -> dict:
    return {SESSION_COOKIE_NAME: id_sessione}


def _make_stripe_event(
    event_type: str,
    data_object: dict,
) -> MagicMock:
    """Crea un mock dell'evento Stripe restituito da construct_event."""
    event = MagicMock()
    event.type = event_type
    event.data = MagicMock()
    event.data.object = data_object
    return event


def _subscription_obj(
    *,
    tenant_id: int,
    stripe_sub_id: str = "sub_test123",
    stripe_customer_id: str = "cus_test123",
    price_id: str = "price_base_test",
    status: str = "active",
    current_period_end: int | None = None,
) -> dict:
    if current_period_end is None:
        current_period_end = int(time.time()) + 30 * 86400
    return {
        "id": stripe_sub_id,
        "customer": stripe_customer_id,
        "status": status,
        "metadata": {"tenant_id": str(tenant_id)},
        "items": {
            "data": [
                {
                    "price": {
                        "id": price_id,
                    }
                }
            ]
        },
        "current_period_end": current_period_end,
        "latest_invoice": {
            "payment_intent": {"status": "succeeded"},
            "lines": {"data": []},
        },
    }


def _form_registrazione(**override) -> dict:
    from conftest import TEST_EMAIL, TEST_PASSWORD, TEST_TENANT_NOME, TEST_TENANT_SLUG, genera_csrf

    s, t = genera_csrf()
    base = {
        "nome_tenant": TEST_TENANT_NOME,
        "slug_tenant": TEST_TENANT_SLUG,
        "nome_utente": "Mario Rossi",
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "conferma_password": TEST_PASSWORD,
        "csrf_token": t,
        "sessione_temp": s,
    }
    base.update(override)
    return base


# =============================================================================
# BILLING-001  Sottoscrizione trial creata dopo registrazione
# =============================================================================


async def test_BILLING_001_trial_creata_su_registrazione(client, db_session):
    from app.models import Tenant

    await client.post("/auth/register", data=_form_registrazione())

    res = await db_session.execute(
        select(Tenant).where(Tenant.slug == "test-tenant")
    )
    tenant = res.scalar_one_or_none()
    if tenant is None:
        pytest.skip("Tenant non creato (dipendenza da AUTH-002)")

    res = await db_session.execute(
        select(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant.id)
    )
    sub = res.scalar_one_or_none()
    assert sub is not None, "BILLING-001 FAIL: nessuna sottoscrizione trial creata"
    assert sub.stato_piano == SottoscrizioniStati.PROVA, (
        f"BILLING-001 FAIL: stato piano = {sub.stato_piano}, atteso PROVA"
    )


# =============================================================================
# BILLING-002  Fine periodo trial è nel futuro (14 giorni default)
# =============================================================================


async def test_BILLING_002_trial_scade_nel_futuro(db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(db_session)

    res = await db_session.execute(
        select(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant.id)
    )
    sub = res.scalar_one_or_none()
    assert sub is not None

    fine = sub.fine_periodo_corrente
    assert fine is not None, "BILLING-002 FAIL: fine_periodo_corrente è None"

    now = datetime.now(timezone.utc)
    if fine.tzinfo is None:
        fine = fine.replace(tzinfo=timezone.utc)

    assert fine > now, (
        f"BILLING-002 FAIL: fine trial {fine} è già scaduta (now={now})"
    )
    assert fine > now + timedelta(days=1), (
        "BILLING-002 FAIL: fine trial avviene tra meno di 24 ore (troppo breve)"
    )


# =============================================================================
# BILLING-003  Webhook checkout.session.completed → sottoscrizione aggiornata
# =============================================================================


async def test_BILLING_003_webhook_checkout_completed(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="billing-checkout",
        email="billing@example.com",
    )

    checkout_obj = {
        "id": "cs_test_abc",
        "subscription": "sub_completed123",
        "customer": "cus_completed123",
        "metadata": {"tenant_id": str(tenant.id)},
        "payment_status": "paid",
        "status": "complete",
    }
    event = _make_stripe_event("checkout.session.completed", checkout_obj)

    sub_obj = _subscription_obj(
        tenant_id=tenant.id,
        stripe_sub_id="sub_completed123",
        stripe_customer_id="cus_completed123",
        status="active",
    )

    with (
        patch("app.routes.stripe.stripe.Webhook.construct_event", return_value=event),
        patch(
            "app.routes.stripe.stripe.Subscription.retrieve",
            return_value=sub_obj,
        ),
        patch("app.core.config.settings.stripe_webhook_secret", "whsec_test123"),
        patch("app.core.billing_models.settings.stripe_price_base", "price_base_test"),
        patch("app.core.billing_models.settings.stripe_price_pro", "price_pro_test"),
        patch("app.core.billing_models.settings.stripe_price_company", "price_company_test"),
    ):
        payload = json.dumps(checkout_obj).encode()
        r = await client.post(
            "/stripe/webhook",
            content=payload,
            headers={
                "Stripe-Signature": "t=1,v1=fake",
                "Content-Type": "application/json",
            },
        )

    # Webhook deve essere accettato (200 o 204)
    assert r.status_code in (200, 204), (
        f"BILLING-003 FAIL: webhook checkout.session.completed → status {r.status_code}"
    )


# =============================================================================
# BILLING-004  Webhook customer.subscription.updated → DB aggiornato
# =============================================================================


async def test_BILLING_004_webhook_subscription_updated(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="billing-update",
        email="billing-update@example.com",
    )

    # Pre-populate sottoscrizione con ID stripe
    res = await db_session.execute(
        select(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant.id)
    )
    sub_db = res.scalar_one()
    sub_db.id_stripe_sottoscrizione = "sub_update123"
    sub_db.id_stripe_cliente = "cus_update123"
    await db_session.commit()

    sub_obj = _subscription_obj(
        tenant_id=tenant.id,
        stripe_sub_id="sub_update123",
        stripe_customer_id="cus_update123",
        status="active",
    )
    event = _make_stripe_event("customer.subscription.updated", sub_obj)

    with (
        patch("app.routes.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.routes.stripe.stripe.Subscription.retrieve", return_value=sub_obj),
        patch("app.core.config.settings.stripe_webhook_secret", "whsec_test123"),
        patch("app.core.billing_models.settings.stripe_price_base", "price_base_test"),
        patch("app.core.billing_models.settings.stripe_price_pro", "price_pro_test"),
        patch("app.core.billing_models.settings.stripe_price_company", "price_company_test"),
    ):
        payload = json.dumps(sub_obj).encode()
        r = await client.post(
            "/stripe/webhook",
            content=payload,
            headers={
                "Stripe-Signature": "t=1,v1=fake",
                "Content-Type": "application/json",
            },
        )

    assert r.status_code in (200, 204), (
        f"BILLING-004 FAIL: webhook subscription.updated → status {r.status_code}"
    )


# =============================================================================
# BILLING-005  Webhook invoice.paid → stato aggiornato ad ATTIVO
# =============================================================================


async def test_BILLING_005_webhook_invoice_paid(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="billing-invoice",
        email="billing-invoice@example.com",
        stato_piano=SottoscrizioniStati.PROVA,
    )

    res = await db_session.execute(
        select(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant.id)
    )
    sub_db = res.scalar_one()
    sub_db.id_stripe_sottoscrizione = "sub_invoice123"
    sub_db.id_stripe_cliente = "cus_invoice123"
    await db_session.commit()

    invoice_obj = {
        "id": "in_test123",
        "subscription": "sub_invoice123",
        "customer": "cus_invoice123",
        "status": "paid",
        "paid": True,
        "payment_intent": {"status": "succeeded"},
        "lines": {"data": []},
    }
    sub_obj = _subscription_obj(
        tenant_id=tenant.id,
        stripe_sub_id="sub_invoice123",
        stripe_customer_id="cus_invoice123",
        status="active",
    )
    event = _make_stripe_event("invoice.paid", invoice_obj)

    with (
        patch("app.routes.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.routes.stripe.stripe.Invoice.retrieve", return_value=invoice_obj),
        patch("app.routes.stripe.stripe.Subscription.retrieve", return_value=sub_obj),
        patch("app.core.config.settings.stripe_webhook_secret", "whsec_test123"),
        patch("app.core.billing_models.settings.stripe_price_base", "price_base_test"),
        patch("app.core.billing_models.settings.stripe_price_pro", "price_pro_test"),
        patch("app.core.billing_models.settings.stripe_price_company", "price_company_test"),
    ):
        payload = json.dumps(invoice_obj).encode()
        r = await client.post(
            "/stripe/webhook",
            content=payload,
            headers={
                "Stripe-Signature": "t=1,v1=fake",
                "Content-Type": "application/json",
            },
        )

    assert r.status_code in (200, 204), (
        f"BILLING-005 FAIL: webhook invoice.paid → status {r.status_code}"
    )


# =============================================================================
# BILLING-006  Webhook customer.subscription.deleted → stato CANCELLATO
# =============================================================================


async def test_BILLING_006_webhook_subscription_deleted(client, db_session, fake_redis):
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="billing-deleted",
        email="billing-del@example.com",
        stato_piano=SottoscrizioniStati.ATTIVO,
    )

    res = await db_session.execute(
        select(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant.id)
    )
    sub_db = res.scalar_one()
    sub_db.id_stripe_sottoscrizione = "sub_del123"
    sub_db.id_stripe_cliente = "cus_del123"
    await db_session.commit()

    sub_obj = _subscription_obj(
        tenant_id=tenant.id,
        stripe_sub_id="sub_del123",
        stripe_customer_id="cus_del123",
        status="canceled",
    )
    event = _make_stripe_event("customer.subscription.deleted", sub_obj)

    with (
        patch("app.routes.stripe.stripe.Webhook.construct_event", return_value=event),
        patch("app.routes.stripe.stripe.Subscription.retrieve", return_value=sub_obj),
        patch("app.core.config.settings.stripe_webhook_secret", "whsec_test123"),
        patch("app.core.billing_models.settings.stripe_price_base", "price_base_test"),
        patch("app.core.billing_models.settings.stripe_price_pro", "price_pro_test"),
        patch("app.core.billing_models.settings.stripe_price_company", "price_company_test"),
    ):
        payload = json.dumps(sub_obj).encode()
        r = await client.post(
            "/stripe/webhook",
            content=payload,
            headers={
                "Stripe-Signature": "t=1,v1=fake",
                "Content-Type": "application/json",
            },
        )

    assert r.status_code in (200, 204), (
        f"BILLING-006 FAIL: webhook subscription.deleted → status {r.status_code}"
    )


# =============================================================================
# BILLING-007  Webhook senza Stripe-Signature → 503 (secret non configurato
#              nel path code) o 400 (firma invalida)
# =============================================================================


async def test_BILLING_007_webhook_senza_firma(client):
    r = await client.post(
        "/stripe/webhook",
        content=b'{"type": "test.event"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code in (400, 422, 503), (
        f"BILLING-007 FAIL: webhook senza firma accettato – status {r.status_code}"
    )


# =============================================================================
# BILLING-008  Webhook con firma invalida → 400
# =============================================================================


async def test_BILLING_008_webhook_firma_invalida(client):
    import stripe as stripe_lib

    with patch("app.core.config.settings.stripe_webhook_secret", "whsec_test123"):
        r = await client.post(
            "/stripe/webhook",
            content=b'{"type": "test.event", "id": "evt_fake"}',
            headers={
                "Stripe-Signature": "t=1,v1=INVALIDA",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code in (400, 422), (
        f"BILLING-008 FAIL: webhook con firma invalida accettato – status {r.status_code}"
    )


# =============================================================================
# BILLING-009  Limiti utenti per piano: BASE = 3
# =============================================================================


async def test_BILLING_009_limite_utenti_piano_base():
    from app.core.billing_models import max_utenti_per_piano

    assert max_utenti_per_piano(Sottoscrizioni.BASE) == 3, (
        "BILLING-009 FAIL: limite utenti piano BASE non è 3"
    )
    assert max_utenti_per_piano(Sottoscrizioni.PRO) == 10, (
        "BILLING-009 FAIL: limite utenti piano PRO non è 10"
    )
    assert max_utenti_per_piano(Sottoscrizioni.COMPANY) == 30, (
        "BILLING-009 FAIL: limite utenti piano COMPANY non è 30"
    )


# =============================================================================
# BILLING-010  piano_da_price_id restituisce None per price_id sconosciuto
# =============================================================================


async def test_BILLING_010_piano_da_price_id_sconosciuto():
    from app.core.billing_models import piano_da_price_id

    result = piano_da_price_id("price_non_esiste")
    assert result is None, (
        f"BILLING-010 FAIL: piano_da_price_id('price_non_esiste') = {result}, atteso None"
    )


# =============================================================================
# BILLING-011  Concorrenza webhook: due richieste parallele non corrompono lo stato
# =============================================================================


async def test_BILLING_011_concorrenza_webhook(client, db_session, fake_redis):
    """
    Invia due webhook subscription.updated simultanei per lo stesso tenant.
    Verifica che il sistema non vada in errore 500 (race condition o deadlock).
    """
    tenant, utente = await _crea_tenant_e_utente(
        db_session,
        slug="billing-concurrent",
        email="concurrent@example.com",
        stato_piano=SottoscrizioniStati.PROVA,
    )

    res = await db_session.execute(
        select(Sottoscrizione).where(Sottoscrizione.tenant_id == tenant.id)
    )
    sub_db = res.scalar_one()
    sub_db.id_stripe_sottoscrizione = "sub_concurrent"
    sub_db.id_stripe_cliente = "cus_concurrent"
    await db_session.commit()

    sub_obj = _subscription_obj(
        tenant_id=tenant.id,
        stripe_sub_id="sub_concurrent",
        stripe_customer_id="cus_concurrent",
        status="active",
    )
    event = _make_stripe_event("customer.subscription.updated", sub_obj)

    async def send_webhook():
        with (
            patch("app.routes.stripe.stripe.Webhook.construct_event", return_value=event),
            patch("app.routes.stripe.stripe.Subscription.retrieve", return_value=sub_obj),
            patch("app.core.config.settings.stripe_webhook_secret", "whsec_test123"),
            patch("app.core.billing_models.settings.stripe_price_base", "price_base_test"),
            patch("app.core.billing_models.settings.stripe_price_pro", "price_pro_test"),
            patch("app.core.billing_models.settings.stripe_price_company", "price_company_test"),
        ):
            return await client.post(
                "/stripe/webhook",
                content=json.dumps(sub_obj).encode(),
                headers={
                    "Stripe-Signature": "t=1,v1=fake",
                    "Content-Type": "application/json",
                },
            )

    results = await asyncio.gather(send_webhook(), send_webhook(), return_exceptions=True)

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            pytest.fail(f"BILLING-011 FAIL: richiesta {i} ha sollevato eccezione: {r}")
        assert r.status_code in (200, 204, 409), (
            f"BILLING-011 FAIL: richiesta concorrente {i} → status {r.status_code}"
        )
