// =============================================================================
// k6/test_login.js
// =============================================================================

import http from 'k6/http'
import { check, sleep } from 'k6'

const BASE_URL = 'http://admin.localhost:8000'

export const options = {
  vus: 500,        // x utenti virtuali
  duration: '30s', // durata del test
}

export default function () {

  // ---- Login POST ----------------------------------------------------------
  const loginRes = http.post(
    `${BASE_URL}/auth/login`,
    {
      email: 'info@spotexsrl.it',
      password: 'WtQ5i8h20@',
      next: '/',
    },
    {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      redirects: 0, // blocca il redirect per ispezionare il 303
    }
  )

  // ---- Verifica risposta login ---------------------------------------------
  check(loginRes, {
    'login status è 303':      r => r.status === 303,
    'header Location presente': r => r.headers['Location'] !== undefined,
    'cookie session_user_id o id_sessione_utente impostato': r =>
      r.cookies['id_sessione_utente'] !== undefined ||
      r.cookies['session_user_id'] !== undefined,
  })

  // ---- Segui il redirect manualmente con cookie ---------------------------
  const cookieName = loginRes.cookies['id_sessione_utente']
    ? 'id_sessione_utente'
    : 'session_user_id'

  const cookieValue = loginRes.cookies[cookieName]
    ? loginRes.cookies[cookieName][0].value
    : null

  if (!cookieValue) {
    return
  }

  const redirectUrl = loginRes.headers['Location']

  const dashboardRes = http.get(
    `${BASE_URL}${redirectUrl}`,
    {
      headers: {
        Cookie: `${cookieName}=${cookieValue}`,
      },
    }
  )

  // ---- Verifica dashboard -------------------------------------------------
  check(dashboardRes, {
    'dashboard status è 200':    r => r.status === 200,
    'dashboard contiene HTML':   r => r.headers['Content-Type'].includes('text/html'),
  })

  sleep(1)
}
