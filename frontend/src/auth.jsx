import axios from 'axios';
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const TOKEN_KEY = 'smartspend_token';
const USER_KEY = 'smartspend_user';
const INVALID_SESSION = 'smartspend:invalid-session';
const renderApiOrigin = import.meta.env.VITE_RENDER_API_ORIGIN;

export const api = axios.create({
  baseURL: renderApiOrigin ? `${renderApiOrigin.replace(/\/$/, '')}/api` :
    (import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://127.0.0.1:5000/api' : '/api')),
  timeout: 15000,
});

const storedToken = () => sessionStorage.getItem(TOKEN_KEY);

api.interceptors.request.use(config => {
  const token = storedToken();
  if (token && !config.headers.Authorization && !config.skipSessionAuth) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(response => response, error => {
  const headers = error.config?.headers;
  const authorization = headers?.get?.('Authorization') ?? headers?.Authorization;
  const token = storedToken();
  if (!error.config?.skipSessionCleanup && token && authorization === `Bearer ${token}` &&
      error.response?.status === 401 && error.response?.data?.code === 'invalid_session') {
    window.dispatchEvent(new CustomEvent(INVALID_SESSION, {
      detail: { token, notice: error.response.data.error },
    }));
  }
  return Promise.reject(error);
});

export const errorText = error => error.response?.data?.error ||
  (error.code === 'ECONNABORTED' ? 'SmartSpend took too long to respond. Please try again.' :
    'Could not connect to SmartSpend. Check your connection and try again.');

const Auth = createContext(null);
export const useAuth = () => useContext(Auth);

export function AuthProvider({ children }) {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [restoring, setRestoring] = useState(() => Boolean(storedToken()));
  const [restoreError, setRestoreError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const currentToken = storedToken();

  const clear = useCallback((token, notice) => {
    if (token !== storedToken()) return;
    let accountId;
    try {
      accountId = JSON.parse(sessionStorage.getItem(USER_KEY))?.id;
    } catch {
      // Discard the invalid cached account below.
    }
    if (accountId) sessionStorage.removeItem(`smartspend_chat:${accountId}`);
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
    setUser(null);
    setRestoring(false);
    setRestoreError('');
    navigate('/login', { replace: true, state: notice ? { notice } : null });
  }, [navigate]);

  useEffect(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    const invalidate = ({ detail }) => clear(detail.token, detail.notice);
    window.addEventListener(INVALID_SESSION, invalidate);
    return () => window.removeEventListener(INVALID_SESSION, invalidate);
  }, [clear]);

  useEffect(() => {
    if (!restoring) return;
    const token = storedToken();
    if (!token) {
      setRestoring(false);
      return;
    }
    const controller = new AbortController();
    api.get('/auth/me', { signal: controller.signal, headers: { Authorization: `Bearer ${token}` } })
      .then(({ data }) => {
        if (controller.signal.aborted || token !== storedToken()) return;
        sessionStorage.setItem(USER_KEY, JSON.stringify(data.user));
        setUser(data.user);
        setRestoring(false);
      })
      .catch(error => {
        if (controller.signal.aborted || token !== storedToken()) return;
        if (error.response?.status === 401) {
          clear(token, error.response?.data?.error);
        } else {
          setRestoreError(errorText(error));
          setRestoring(false);
        }
      });
    return () => controller.abort();
  }, [attempt, clear, restoring]);

  function save({ access_token: token, user: account }) {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(account));
    setUser(account);
    setRestoring(false);
    setRestoreError('');
  }

  function updateUser(account) {
    if (!currentToken || currentToken !== storedToken()) return;
    sessionStorage.setItem(USER_KEY, JSON.stringify(account));
    setUser(account);
  }

  function signOut() {
    const token = storedToken();
    clear(token);
    if (token) {
      api.post('/auth/logout', {}, {
        headers: { Authorization: `Bearer ${token}` },
        skipSessionCleanup: true,
      }).catch(() => {
        // The browser session is already cleared, even if the network is unavailable.
      });
    }
  }

  if (restoring || restoreError) {
    return <main className="auth-screen"><section className="auth-card">
      {restoring ? <p role="status">Checking your session…</p> : <>
        <p role="alert" className="form-error">{restoreError}</p>
        <div className="form-actions">
          <button type="button" className="primary-button" onClick={() => {
            setRestoreError('');
            setRestoring(true);
            setAttempt(value => value + 1);
          }}>Try again</button>
          <button type="button" className="secondary-button" onClick={signOut}>Sign in</button>
        </div>
      </>}
    </section></main>;
  }
  return <Auth.Provider value={{ user, save, signOut, setUser: updateUser }}>{children}</Auth.Provider>;
}
