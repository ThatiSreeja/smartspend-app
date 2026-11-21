import AssistantChat from './AssistantChat';
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { api, AuthProvider, errorText, useAuth } from './auth';
import { Activity, ArrowDownLeft, ArrowUpRight, Bell, Bot, BriefcaseBusiness, CarFront, ChevronDown, CircleHelp, CreditCard, Home, LogOut, Menu, Plus, Search, Settings, ShoppingBag, Utensils, Wallet, X } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const money = (amount, currency = 'INR') => new Intl.NumberFormat('en-IN', { style: 'currency', currency }).format(Number(amount || 0));

function SignIn({ register = false }) {
  const { user, save } = useAuth();
  const navigate = useNavigate();
  const { state } = useLocation();
  const requestPending = useRef(null);
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => () => requestPending.current?.abort(), []);
  if (user) return <Navigate to="/" replace />;

  async function submit(event) {
    event.preventDefault();
    if (requestPending.current) return;
    const controller = new AbortController();
    requestPending.current = controller;
    setBusy(true);
    setError('');
    try {
      const { data } = await api.post(`/auth/${register ? 'register' : 'login'}`, form, {
        signal: controller.signal, skipSessionAuth: true,
      });
      if (controller.signal.aborted) return;
      save(data);
      navigate('/', { replace: true });
    } catch (failure) {
      if (!controller.signal.aborted) setError(errorText(failure));
    } finally {
      requestPending.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return <div className="auth-screen"><div className="auth-card"><Link className="brand auth-brand" to="/"><span className="brand-mark"><Wallet size={19} /></span><span>smart<span>spend</span></span></Link><p className="eyebrow">YOUR MONEY, MADE CLEAR</p><h1>{register ? 'Create your account' : 'Welcome back'}</h1><p className="subtitle">{register ? 'Start managing your money with clarity.' : 'Sign in to see your personal dashboard.'}</p>{state?.notice && <p role="status" className="form-error">{state.notice}</p>}<form onSubmit={submit} className="form-stack">{register && <label>Your name<input autoComplete="name" required minLength="2" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>}<label>Email address<input type="email" autoComplete="email" required value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></label><label>Password<input type="password" autoComplete={register ? 'new-password' : 'current-password'} required minLength={8} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /><small>At least 8 characters</small></label>{!register && <Link className="forgot-link" to="/forgot-password">Forgot password?</Link>}{error && <div role="alert" className="form-error">{error}</div>}<button className="primary-button full-button" disabled={busy}>{busy ? 'Please wait…' : register ? 'Create account' : 'Sign in'}</button></form><p className="auth-switch">{register ? 'Already have an account?' : 'New to SmartSpend?'} <Link to={register ? '/login' : '/register'}>{register ? 'Sign in' : 'Create an account'}</Link></p><p className="secure-note">Your password is hashed and never stored in plain text.</p></div></div>;
}

function ForgotPassword() {
  const [email, setEmail] = useState(''), [message, setMessage] = useState(''), [error, setError] = useState('');
  const submit = async e => { e.preventDefault(); setError(''); try { const { data } = await api.post('/auth/forgot-password', { email }); setMessage(data.message); } catch (e) { setError(errorText(e)); } };
  return <div className="auth-screen"><div className="auth-card"><Link className="brand auth-brand" to="/login"><span className="brand-mark"><Wallet size={19} /></span><span>smart<span>spend</span></span></Link><h1>Reset your password</h1><p className="subtitle">Enter your account email and we’ll send a reset link if email delivery is configured.</p><form className="form-stack" onSubmit={submit}><label>Email address<input type="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>{message && <div className="form-success">{message}</div>}<ErrorBox>{error}</ErrorBox><button className="primary-button full-button">Send reset link</button></form><p className="auth-switch"><Link to="/login">Back to sign in</Link></p></div></div>;
}
function ResetPassword() {
  const [params] = useSearchParams(); const [password, setPassword] = useState(''), [message, setMessage] = useState(''), [error, setError] = useState('');
  const submit = async e => { e.preventDefault(); setError(''); try { const { data } = await api.post('/auth/reset-password', { token: params.get('token'), password }); setMessage(data.message); } catch (e) { setError(errorText(e)); } };
  return <div className="auth-screen"><div className="auth-card"><Link className="brand auth-brand" to="/login"><span className="brand-mark"><Wallet size={19} /></span><span>smart<span>spend</span></span></Link><h1>Choose a new password</h1><form className="form-stack" onSubmit={submit}><label>New password<input type="password" minLength="8" required value={password} onChange={e => setPassword(e.target.value)} /></label>{message && <div className="form-success">{message} <Link to="/login">Sign in</Link></div>}<ErrorBox>{error}</ErrorBox><button className="primary-button full-button">Reset password</button></form></div></div>;
}

const Navigation = createContext(null);

function Sidebar({ onNavigate, closeButton }) {
  const { user, signOut } = useAuth();
  const links = [
    ['Overview', '/', Home], ['Transactions', '/transactions', CreditCard],
    ['Budgets', '/budgets', Wallet], ['AI assistant', '/assistant', Bot],
    ['Reports', '/reports', Activity], ['Categories', '/categories', ShoppingBag],
  ];
  return <aside className="sidebar">
    <div className="sidebar-heading">
      <Link className="brand" to="/" onClick={onNavigate}><span className="brand-mark"><Wallet size={19} /></span><span>smart<span>spend</span></span></Link>
      {closeButton}
    </div>
    <div className="workspace-label">WORKSPACE</div>
    <nav aria-label="Workspace">{links.map(([label, to, Icon]) =>
      <NavLink end={to === '/'} key={to} to={to} onClick={onNavigate}
        className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
        <Icon size={18} /><span>{label}</span>{label === 'AI assistant' && <span className="new-badge" aria-hidden="true">AI</span>}
      </NavLink>
    )}</nav>
    <div className="sidebar-bottom">
      <NavLink className="nav-link" to="/profile" onClick={onNavigate}><Settings size={18} /><span>Profile & settings</span></NavLink>
      <button type="button" className="nav-link signout-link" onClick={signOut}><LogOut size={18} /><span>Sign out</span></button>
      <div className="profile">
        <div className="avatar">{user?.name?.slice(0, 1).toUpperCase()}</div>
        <div className="profile-copy"><strong>{user?.name}</strong><span>{user?.email}</span></div>
      </div>
    </div>
  </aside>;
}

function AppLayout({ children }) {
  const drawer = useRef(null);
  const [mobile, setMobile] = useState(() => window.matchMedia?.('(max-width: 850px)').matches ?? false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    const viewport = window.matchMedia?.('(max-width: 850px)');
    if (!viewport) return;
    function change(event) {
      if (!event.matches) drawer.current?.close();
      setDrawerOpen(false);
      setMobile(event.matches);
    }
    viewport.addEventListener('change', change);
    return () => viewport.removeEventListener('change', change);
  }, []);

  useEffect(() => {
    if (drawer.current?.open) drawer.current.close();
  }, [pathname]);

  function openDrawer() {
    if (!drawer.current?.open) {
      drawer.current?.showModal();
      setDrawerOpen(true);
    }
  }

  const closeDrawer = () => drawer.current?.close();
  return <Navigation.Provider value={{ mobile, drawerOpen, openDrawer }}>
    <div className="app-shell">
      {mobile ? <dialog id="workspace-navigation" className="navigation-drawer" ref={drawer}
        aria-label="Workspace navigation" onClose={() => { if (!drawer.current?.open) setDrawerOpen(false); }}
        onClick={event => { if (event.target === event.currentTarget) closeDrawer(); }}>
        <Sidebar onNavigate={closeDrawer} closeButton={
          <button type="button" className="menu-button" aria-label="Close navigation" onClick={closeDrawer}><X size={22} /></button>
        } />
      </dialog> : <Sidebar />}
      {children}
    </div>
  </Navigation.Provider>;
}

function Shell({ children, title = 'Overview', className = '' }) {
  const { user } = useAuth();
  const { mobile, drawerOpen, openDrawer } = useContext(Navigation);
  return <main className={`main ${className}`}>
    <header className="topbar">
      <div className="topbar-start">
        {mobile && <button type="button" className="menu-button" aria-label="Open navigation"
          aria-controls="workspace-navigation" aria-expanded={drawerOpen} onClick={openDrawer}><Menu size={23} /></button>}
        <div className="breadcrumbs">SmartSpend <span>/</span> <strong>{title}</strong></div>
      </div>
      <div className="top-actions"><div className="top-avatar">{user?.name?.slice(0, 1).toUpperCase()}</div></div>
    </header>
    <div className="page-content">{children}</div>
  </main>;
}

function Protected({ children }) { const { user } = useAuth(); return user ? children : <Navigate to="/login" replace />; }
function PageHeading({ eyebrow = 'YOUR FINANCES', title, subtitle, action }) { return <div className="welcome-row"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="subtitle">{subtitle}</p></div>{action}</div>; }
function ErrorBox({ children }) { return children ? <div className="form-error page-error">{children}</div> : null; }

function Dashboard() {
  const { user } = useAuth();
  const [period, setPeriod] = useState(() => {
    const now = new Date();
    return { month: now.getMonth() + 1, year: now.getFullYear() };
  });
  const [result, setResult] = useState(null);
  const { month, year } = period;
  const validYear = Number.isInteger(year) && year >= 1900 && year <= 9998;
  const label = month === 'all' ? String(year) : `${new Date(2000, month - 1, 1).toLocaleString('en', { month: 'long' })} ${year}`;
  const data = result?.data;
  const recent = data?.recent ?? [];
  const empty = data?.transaction_count === 0;
  const transactionsUrl = data?.date_filters ? `/transactions?${new URLSearchParams(data.date_filters)}` : null;

  useEffect(() => {
    if (!validYear) return;
    const controller = new AbortController();
    api.get('/dashboard', { params: { month, year }, signal: controller.signal })
      .then(({ data }) => {
        if (!controller.signal.aborted) setResult({ data });
      })
      .catch(error => {
        if (!controller.signal.aborted) setResult({ error: errorText(error) });
      });
    return () => controller.abort();
  }, [month, year, validYear]);

  function selectPeriod(update) {
    if ((update.month ?? month) === month && (update.year ?? year) === year) return;
    setResult(null);
    setPeriod(current => ({ ...current, ...update }));
  }
  return <Shell><PageHeading eyebrow={new Date().toLocaleDateString('en-IN', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).toUpperCase()} title={`Good ${new Date().getHours() < 12 ? 'morning' : 'afternoon'}, ${user?.name?.split(' ')[0]}`} subtitle="Your overview, calculated from your saved transactions." action={<Link to="/transactions" className="primary-button"><Plus size={17} /> Add transaction</Link>} /><ErrorBox>{result?.error}</ErrorBox>
    {!validYear ? <p role="status">Enter a year from 1900 to 9998.</p> : !result && <p role="status">Loading dashboard for {label}?</p>}
    <div className="period-controls"><label>Month<select value={period.month} onChange={e => selectPeriod({ month: e.target.value === 'all' ? 'all' : Number(e.target.value) })}><option value="all">Full year</option>{Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{new Date(2000, i, 1).toLocaleString('en', { month: 'long' })}</option>)}</select></label><label>Year<input type="number" min="1900" max="9998" value={period.year} onChange={e => selectPeriod({ year: e.target.value === '' ? '' : Number(e.target.value) })} /></label></div>
    <section className="stats-grid"><Stat title="Income" value={data ? money(data.income, user?.currency) : undefined} icon={<ArrowDownLeft size={17} />} tone="green" /><Stat title="Expenses" value={data ? money(data.expenses, user?.currency) : undefined} icon={<ArrowUpRight size={17} />} tone="orange" /><Stat title="Remaining balance" value={data ? money(data.balance, user?.currency) : undefined} icon={<Wallet size={17} />} tone="purple" /><Stat title="Savings rate" value={data ? `${data.savings_rate ?? 0}%` : undefined} icon={<Activity size={17} />} tone="blue" /></section>
    <section className="content-grid"><article className="panel chart-panel"><div className="panel-heading"><div><h2>Income & expenses</h2><p>Monthly trend for {year}</p></div></div><div className="chart-legend"><span><i className="legend-income" /> Income</span><span><i className="legend-expense" /> Expenses</span></div>{data && <div className="chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={data.months ?? []} margin={{ top: 15, right: 12, left: 0, bottom: 5 }}><CartesianGrid vertical={false} stroke="#eef0f5" /><XAxis dataKey="month" interval={0} angle={-40} textAnchor="end" height={36} tickFormatter={value => value.slice(0, 3)} axisLine={false} tickLine={false} tick={{ fill: '#9298a8', fontSize: 11 }} /><YAxis width={44} axisLine={false} tickLine={false} tickFormatter={v => `₹${v}`} tick={{ fill: '#9298a8', fontSize: 10 }} /><Tooltip formatter={v => money(v, user?.currency)} /><Bar dataKey="income" name="Income" fill="#7969e8" maxBarSize={40} /><Bar dataKey="expenses" name="Expenses" fill="#42b99b" maxBarSize={40} /></BarChart></ResponsiveContainer></div>}</article><article className="panel category-panel"><div className="panel-heading"><div><h2>Spending by category</h2><p>Selected period</p></div></div>{data?.categories?.length ? <div className="category-bars">{data.categories.map((item, i) => <div key={item.name}><div className="category-label"><span>{item.name}</span><b>{money(item.amount, user?.currency)}</b></div><div className="bar"><i style={{ width: `${Math.max(3, item.amount / (data.expenses || 1) * 100)}%`, background: ['#8e7bea', '#50bda0', '#f0a16c', '#6eaae9'][i % 4] }} /></div></div>)}</div> : data && <Empty text="No expenses for this period." />}</article></section>
    <section className="panel transaction-panel"><div className="panel-heading"><div><h2>Recent transactions</h2><p>Latest entries for {label}</p></div>{transactionsUrl && <Link className="text-link" to={transactionsUrl}>View all →</Link>}</div>{recent.length ? <TransactionRows rows={recent} currency={user?.currency} /> : empty && <Empty text={`No transactions found for ${label}.`} />}</section>
  </Shell>;
}
function Stat({ title, value, icon, tone }) { return <article className="stat-card"><div className="stat-top"><span>{title}</span><span className={`stat-icon ${tone}`}>{icon}</span></div><div className="stat-value">{value ?? '—'}</div><div className="stat-foot">From saved records</div></article>; }
function Empty({ text }) { return <div className="empty-state">{text}</div>; }
function TransactionRows({ rows, currency, onEdit, onDelete }) { return <div className="transaction-list">{rows.map(item => <div className="transaction-row" key={item.id}><div className={`transaction-icon ${item.type === 'income' ? 'mint' : 'peach'}`}>{item.type === 'income' ? <ArrowDownLeft size={16} /> : <ShoppingBag size={16} />}</div><div className="transaction-copy"><strong>{item.description || item.category}</strong><span>{item.category} · {item.transaction_date}</span></div><strong className={item.type === 'income' ? 'amount-in' : 'amount-out'}>{item.type === 'income' ? '+' : '−'}{money(item.amount, currency)}</strong>{(onEdit || onDelete) && <div className="transaction-actions">{onEdit && <button className="row-action" onClick={() => onEdit(item)}>Edit</button>}{onDelete && <button className="row-action danger" onClick={() => onDelete(item.id)}>Delete</button>}</div>}</div>)}</div>; }

function TransactionForm({ categories, initial, onSaved, onCancel }) {
  const [form, setForm] = useState(initial || { type: 'expense', amount: '', category_id: '', transaction_date: new Date().toISOString().slice(0, 10), description: '' });
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const choices = categories.filter(c => c.type === form.type);
  useEffect(() => { if (!choices.some(c => c.id === Number(form.category_id))) setForm(f => ({ ...f, category_id: choices[0]?.id || '' })); }, [form.type, categories]);
  const submit = async e => { e.preventDefault(); setBusy(true); setError(''); try { const data = { ...form, category_id: Number(form.category_id) }; if (initial) await api.put(`/transactions/${initial.id}`, data); else await api.post('/transactions', data); onSaved(); } catch (err) { setError(errorText(err)); } finally { setBusy(false); } };
  return <form className="form-stack inline-form" onSubmit={submit}><div className="form-two"><label>Type<select value={form.type} onChange={e => setForm({ ...form, type: e.target.value, category_id: '' })}><option value="expense">Expense</option><option value="income">Income</option></select></label><label>Amount<input type="number" min="0.01" step="0.01" required value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} /></label></div><div className="form-two"><label>Category<select aria-label="Category" required value={form.category_id} onChange={e => setForm({ ...form, category_id: e.target.value })}>{choices.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label><label>Date<input type="date" required value={form.transaction_date} onChange={e => setForm({ ...form, transaction_date: e.target.value })} /></label></div><label>Description<input maxLength="500" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} placeholder="What was this for?" /></label><ErrorBox>{error}</ErrorBox><div className="form-actions"><button type="button" className="secondary-button" onClick={onCancel}>Cancel</button><button className="primary-button" disabled={busy}>{busy ? 'Saving…' : initial ? 'Save changes' : 'Save transaction'}</button></div></form>;
}
function Transactions() {
  const [dateFilters] = useSearchParams();
  const { user } = useAuth(); const [rows, setRows] = useState([]); const [categories, setCategories] = useState([]); const [error, setError] = useState(''); const [editing, setEditing] = useState(null); const [showForm, setShowForm] = useState(false); const [search, setSearch] = useState(''); const [kind, setKind] = useState(''); const [categoryId, setCategoryId] = useState(''), [from, setFrom] = useState(dateFilters.get('from') ?? ''), [to, setTo] = useState(dateFilters.get('to') ?? ''), [sort, setSort] = useState('date_desc'), [page, setPage] = useState(1), [total, setTotal] = useState(0);
  const load = (nextPage = 1, append = false) => api.get('/transactions', { params: { search, type: kind, category_id: categoryId, from, to, sort, page: nextPage } }).then(r => { setRows(old => append ? [...old, ...r.data.items] : r.data.items); setPage(r.data.page); setTotal(r.data.total); setError(''); }).catch(e => setError(errorText(e)));
  useEffect(() => { api.get('/categories').then(r => setCategories(r.data)).catch(e => setError(errorText(e))); }, []); useEffect(() => { load(); }, [search, kind, categoryId, from, to, sort]);
  const remove = async id => { if (!window.confirm('Delete this transaction?')) return; try { await api.delete(`/transactions/${id}`); load(); } catch (e) { setError(errorText(e)); } };
  const saved = () => { setShowForm(false); setEditing(null); load(); };
  const csv = async () => { try { const response = await api.get('/reports/export', { responseType: 'blob' }); const url = URL.createObjectURL(response.data); const a = document.createElement('a'); a.href = url; a.download = 'smartspend-transactions.csv'; a.click(); URL.revokeObjectURL(url); } catch (e) { setError(errorText(e)); } };
  return <Shell title="Transactions"><PageHeading title="Transactions" subtitle="Add, search, and manage your saved income and expenses." action={<button className="primary-button" onClick={() => { setEditing(null); setShowForm(true); }}><Plus size={16} /> Add transaction</button>} /><ErrorBox>{error}</ErrorBox><div className="filters"><label className="search"><Search size={16} /><input aria-label="Search descriptions" placeholder="Search descriptions" value={search} onChange={e => setSearch(e.target.value)} /></label><select aria-label="Transaction type" value={kind} onChange={e => setKind(e.target.value)}><option value="">All types</option><option value="income">Income</option><option value="expense">Expense</option></select><select aria-label="Filter by category" value={categoryId} onChange={e => setCategoryId(e.target.value)}><option value="">All categories</option>{categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select><label className="filter-date">From<input type="date" value={from} onChange={e => setFrom(e.target.value)} /></label><label className="filter-date">To<input type="date" value={to} onChange={e => setTo(e.target.value)} /></label><select aria-label="Sort transactions" value={sort} onChange={e => setSort(e.target.value)}><option value="date_desc">Newest</option><option value="date_asc">Oldest</option><option value="amount_desc">Highest amount</option><option value="amount_asc">Lowest amount</option></select><button className="secondary-button" onClick={csv}>Export CSV</button></div>{(showForm || editing) && <section className="panel form-panel"><div className="panel-heading"><h2>{editing ? 'Edit transaction' : 'New transaction'}</h2><button className="icon-button" aria-label="Close transaction form" onClick={() => { setShowForm(false); setEditing(null); }}><X size={18} /></button></div><TransactionForm categories={categories} initial={editing || undefined} onSaved={saved} onCancel={() => { setShowForm(false); setEditing(null); }} /></section>}<section className="panel transaction-panel">{rows.length ? <TransactionRows rows={rows} currency={user?.currency} onEdit={setEditing} onDelete={remove} /> : <Empty text="No matching transactions. Add your first entry above." />}{rows.length < total && <button className="secondary-button" onClick={() => load(page + 1, true)}>Load more</button>}</section></Shell>;
}

function Budgets() {
  const [categories, setCategories] = useState([]), [rows, setRows] = useState([]), [error, setError] = useState(''); const today = new Date(); const [period, setPeriod] = useState({ month: today.getMonth() + 1, year: today.getFullYear() }); const [form, setForm] = useState({ category_id: '', amount: '' });
  const load = () => api.get('/budgets', { params: period }).then(r => setRows(r.data)).catch(e => setError(errorText(e)));
  useEffect(() => { api.get('/categories').then(r => setCategories(r.data.filter(c => c.type === 'expense'))).catch(e => setError(errorText(e))); }, []); useEffect(() => { load(); }, [period.month, period.year]);
  const save = async e => { e.preventDefault(); try { await api.post('/budgets', { ...form, ...period, category_id: Number(form.category_id) }); setForm({ ...form, amount: '' }); load(); } catch (e) { setError(errorText(e)); } };
  const remove = async id => { try { await api.delete(`/budgets/${id}`); load(); } catch (e) { setError(errorText(e)); } };
  return <Shell title="Budgets"><PageHeading title="Monthly budgets" subtitle="Set category limits and track actual spending." /><ErrorBox>{error}</ErrorBox><div className="period-controls"><label>Month<select value={period.month} onChange={e => setPeriod({ ...period, month: Number(e.target.value) })}>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{new Date(2000, i, 1).toLocaleString('en', { month: 'long' })}</option>)}</select></label><label>Year<input type="number" value={period.year} onChange={e => setPeriod({ ...period, year: Number(e.target.value) })} /></label></div><section className="panel form-panel"><h2>Create or update a category budget</h2><form className="form-two budget-form" onSubmit={save}><label>Expense category<select required value={form.category_id} onChange={e => setForm({ ...form, category_id: e.target.value })}><option value="">Select category</option>{categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label><label>Monthly limit<input type="number" min="0.01" step="0.01" required value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} /></label><button className="primary-button">Save budget</button></form></section><section className="budget-grid">{rows.map(b => <article className="panel budget-card" key={b.id}><div className="panel-heading"><h2>{b.category}</h2><button className="row-action danger" onClick={() => remove(b.id)}>Delete</button></div><p><strong>{money(b.spent)}</strong> spent of {money(b.amount)}</p><div className="bar budget-bar"><i style={{ width: `${Math.min(100, b.utilization)}%`, background: b.utilization >= 100 ? '#e87979' : b.utilization >= 80 ? '#f0a16c' : '#50bda0' }} /></div><small>{b.utilization}% used · {money(b.remaining)} remaining {b.utilization >= 100 ? '· Over budget' : b.utilization >= 80 ? '· Near limit' : ''}</small></article>)}</section>{!rows.length && <section className="panel"><Empty text="No budgets for this month yet." /></section>}</Shell>;
}

function Reports() {
  const [data, setData] = useState(null), [error, setError] = useState(''); const [period, setPeriod] = useState({ month: new Date().getMonth() + 1, year: new Date().getFullYear() });
  useEffect(() => { api.get('/reports', { params: period }).then(r => { setData(r.data); setError(''); }).catch(e => setError(errorText(e))); }, [period.month, period.year]);
  return <Shell title="Reports"><PageHeading title="Reports & analytics" subtitle="Explore totals and category breakdowns from your saved transactions." /><ErrorBox>{error}</ErrorBox><div className="period-controls"><label>Month<select value={period.month} onChange={e => setPeriod({ ...period, month: e.target.value === 'all' ? 'all' : Number(e.target.value) })}><option value="all">Full year</option>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{new Date(2000, i, 1).toLocaleString('en', { month: 'long' })}</option>)}</select></label><label>Year<input type="number" value={period.year} onChange={e => setPeriod({ ...period, year: Number(e.target.value) })} /></label></div><section className="stats-grid"><Stat title="Income" value={money(data?.income)} icon={<ArrowDownLeft size={17} />} tone="green" /><Stat title="Expenses" value={money(data?.expenses)} icon={<ArrowUpRight size={17} />} tone="orange" /><Stat title="Net" value={money((data?.income || 0) - (data?.expenses || 0))} icon={<Wallet size={17} />} tone="purple" /></section><section className="panel"><div className="panel-heading"><div><h2>Category breakdown</h2><p>Totals from the selected period</p></div></div>{data?.categories?.length ? <div className="report-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={data.categories} margin={{ top: 12, right: 12, left: 0, bottom: 35 }}><CartesianGrid vertical={false} stroke="#eef0f5" /><XAxis dataKey="name" angle={-25} textAnchor="end" interval="preserveStartEnd" minTickGap={10} tick={{ fontSize: 10, fill: '#77798b' }} /><YAxis tick={{ fontSize: 10, fill: '#9298a8' }} /><Tooltip formatter={v => money(v)} /><Legend /><Bar dataKey="amount" name="Total amount" fill="#7969e8" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div> : <Empty text="Reports will populate when you record transactions." />}</section><section className="panel transaction-panel"><div className="panel-heading"><div><h2>Category details</h2><p>Transaction counts and totals</p></div></div>{data?.categories?.length ? <div className="report-table"><div className="report-row report-head"><span>Type</span><span>Category</span><span>Transactions</span><span>Total</span></div>{data.categories.map((r, i) => <div className="report-row" key={i}><span>{r.type}</span><span>{r.name}</span><span>{r.count}</span><strong>{money(r.amount)}</strong></div>)}</div> : <Empty text="No category data for this period." />}</section></Shell>;
}

function Assistant() {
  const { user } = useAuth();
  const sendQuestion = async (body, signal) => {
    const { data } = await api.post('/chat/message', body, { signal, timeout: 15000 });
    return data;
  };
  return <Shell title="AI assistant" className="assistant-page">
    <PageHeading title="Financial assistant" subtitle="Ask about your finances or explore your recorded transactions." />
    <AssistantChat key={user.id} userId={user.id} sendQuestion={sendQuestion} formatError={errorText} />
  </Shell>;
}

function Categories() {
  const [items, setItems] = useState([]), [name, setName] = useState(''), [type, setType] = useState('expense'), [error, setError] = useState('');
  const load = () => api.get('/categories').then(r => setItems(r.data)).catch(e => setError(errorText(e))); useEffect(() => { load(); }, []);
  const add = async e => { e.preventDefault(); try { await api.post('/categories', { name, type }); setName(''); load(); } catch (e) { setError(errorText(e)); } };
  const remove = async id => { try { await api.delete(`/categories/${id}`); load(); } catch (e) { setError(errorText(e)); } };
  return <Shell title="Categories"><PageHeading title="Categories" subtitle="Default categories are ready. Add your own when needed." /><ErrorBox>{error}</ErrorBox><section className="panel form-panel"><form className="form-two" onSubmit={add}><label>Category name<input required maxLength="80" value={name} onChange={e => setName(e.target.value)} /></label><label>Type<select value={type} onChange={e => setType(e.target.value)}><option value="expense">Expense</option><option value="income">Income</option></select></label><button className="primary-button">Add category</button></form></section><section className="panel category-list">{items.map(c => <div className="transaction-row" key={c.id}><div className={`transaction-icon ${c.type === 'income' ? 'mint' : 'peach'}`}>{c.type === 'income' ? <ArrowDownLeft size={16} /> : <ShoppingBag size={16} />}</div><div className="transaction-copy"><strong>{c.name}</strong><span>{c.type}{c.user_id == null ? ' · default' : ''}</span></div>{c.user_id != null && <button className="row-action danger" onClick={() => remove(c.id)}>Delete</button>}</div>)}</section></Shell>;
}

function Profile() {
  const { user, setUser } = useAuth(); const [profile, setProfile] = useState({ name: user?.name || '', email: user?.email || '', currency: user?.currency || 'INR' }); const [pw, setPw] = useState({ current_password: '', new_password: '' }); const [notice, setNotice] = useState(''); const [error, setError] = useState('');
  const save = async e => { e.preventDefault(); try { const { data } = await api.put('/profile', profile); setUser(data.user); setNotice('Profile saved.'); setError(''); } catch (e) { setError(errorText(e)); } };
  const password = async e => { e.preventDefault(); try { const { data } = await api.put('/profile/password', pw); setNotice(data.message); setError(''); setPw({ current_password: '', new_password: '' }); } catch (e) { setError(errorText(e)); } };
  return <Shell title="Profile"><PageHeading title="Profile & settings" subtitle="Manage your account details and security." /><ErrorBox>{error}</ErrorBox>{notice && <div className="form-success">{notice}</div>}<section className="panel form-panel"><h2>Personal details</h2><form className="form-stack" onSubmit={save}><label>Name<input required value={profile.name} onChange={e => setProfile({ ...profile, name: e.target.value })} /></label><label>Email<input type="email" required value={profile.email} onChange={e => setProfile({ ...profile, email: e.target.value })} /></label><label>Currency code<input maxLength="3" required value={profile.currency} onChange={e => setProfile({ ...profile, currency: e.target.value.toUpperCase() })} /></label><button className="primary-button">Save profile</button></form></section><section className="panel form-panel"><h2>Change password</h2><form className="form-stack" onSubmit={password}><label>Current password<input type="password" required value={pw.current_password} onChange={e => setPw({ ...pw, current_password: e.target.value })} /></label><label>New password<input type="password" required minLength="8" value={pw.new_password} onChange={e => setPw({ ...pw, new_password: e.target.value })} /></label><button className="primary-button">Change password</button></form></section></Shell>;
}

function Landing() {
  return <div className="landing-page"><nav className="landing-nav"><Link className="brand" to="/"><span className="brand-mark"><Wallet size={19} /></span><span>smart<span>spend</span></span></Link><div><Link className="secondary-button" to="/login">Sign in</Link><Link className="primary-button" to="/register">Get started</Link></div></nav><section className="landing-hero"><p className="eyebrow">A CLEARER VIEW OF YOUR MONEY</p><h1>Spend with intention.<br /><span>Save with confidence.</span></h1><p>Track your income, stay on top of budgets, and understand where your money goes with personal insights built around your real numbers.</p><Link className="primary-button" to="/register">Create your free account <span>→</span></Link><div className="landing-preview"><div className="landing-preview-top"><span>MONTHLY OVERVIEW</span><span>PRIVATE · YOUR DATA</span></div><div className="landing-preview-cards"><div><small>INCOME</small><strong>Saved from your entries</strong></div><div><small>EXPENSES</small><strong>Grouped by category</strong></div><div><small>BUDGETS</small><strong>Limits that keep you on track</strong></div></div><div className="landing-bars"><i /><i /><i /><i /><i /><i /><i /><i /></div></div></section><section className="landing-features"><article><Wallet /><h2>Know your balance</h2><p>See income, expenses, and savings calculated from your transactions.</p></article><article><Activity /><h2>Build better habits</h2><p>Set category budgets and catch overspending before it adds up.</p></article><article><Bot /><h2>Get useful guidance</h2><p>Ask questions about your own spending summaries and trends.</p></article></section></div>;
}
function RootPage() { const { user } = useAuth(); return user ? <AppLayout><Dashboard /></AppLayout> : <Landing />; }

export default function App() {
  return <AuthProvider><Routes><Route path="/" element={<RootPage />} /><Route path="/login" element={<SignIn />} /><Route path="/register" element={<SignIn register />} /><Route path="/forgot-password" element={<ForgotPassword />} /><Route path="/reset-password" element={<ResetPassword />} /><Route path="*" element={<Protected><AppLayout><Routes><Route path="/transactions" element={<Transactions />} /><Route path="/budgets" element={<Budgets />} /><Route path="/assistant" element={<Assistant />} /><Route path="/reports" element={<Reports />} /><Route path="/categories" element={<Categories />} /><Route path="/profile" element={<Profile />} /><Route path="*" element={<Navigate to="/" replace />} /></Routes></AppLayout></Protected>} /></Routes></AuthProvider>;
}
