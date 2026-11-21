import { useEffect, useRef, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

const prompts = [
  'What is money?', 'Explain artificial intelligence', 'How much did I spend today?',
  'Analyze my May expenses', 'How much did I save this month?', 'Explain inflation and show my expenses',
];

function loadMessages(storageKey) {
  try {
    const messages = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
    return Array.isArray(messages) ? messages : [];
  } catch {
    return [];
  }
}

function FinanceDisplay({ display }) {
  if (!display?.rows?.length) return null;
  const { type, metric, rows } = display;
  if (type === 'transactions') {
    return <div className="chat-table"><table>
      <caption>Matching transactions</caption>
      <thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Amount</th><th>Type</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index}>
        <td>{row.date}</td><td>{row.description || '—'}</td><td>{row.name}</td><td>{row.display}</td><td>{row.type}</td>
      </tr>)}</tbody>
    </table></div>;
  }
  if (type === 'savings') {
    return <dl className="chat-savings">{rows.map(row => <div key={row.name}>
      <dt>{row.name}</dt><dd>{row.display}</dd>
    </div>)}</dl>;
  }
  const summary = display.summary;
  const categoryTable = type === 'categories' && summary ? <div className="chat-table"><table>
      <caption>Expenses by category</caption>
      <thead><tr><th>Category</th><th>Amount</th><th>Transactions</th><th>Share of expenses</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.name}>
        <td>{row.name}</td><td>{row.display}</td><td>{row.count}</td><td>{row.percentage}</td>
      </tr>)}</tbody>
      <tfoot><tr><th>{summary.partial ? 'Selected total' : 'Total'}</th>
        <td>{summary.display}</td><td>{summary.count}</td><td>{summary.percentage}</td>
      </tr></tfoot>
    </table></div> : null;
  if (categoryTable && (summary.partial || rows.length < 2)) return categoryTable;
  const colors = ['#6251c9', '#268a77', '#b65738', '#497fb4', '#a7477a'];
  const data = rows.map((row, index) => ({
    ...row,
    amount: Number(row.amount),
    fill: colors[index % colors.length],
    income: row.count ? Number(row.income) : null,
    expenses: row.count ? Number(row.expenses) : null,
    savings: row.count ? Number(row.savings) : null,
  }));
  return <>{categoryTable}<div className="chat-chart">
    <ResponsiveContainer width="100%" height={215}>
      {type === 'categories' ? <PieChart>
        <Pie data={data} dataKey="amount" nameKey="name" outerRadius={65} />
        <Tooltip /><Legend />
      </PieChart> : type === 'trend' ? <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis width={55} />
        <Tooltip /><Legend /><Line dataKey={metric} stroke={colors[0]} />
      </LineChart> : <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis width={55} />
        <Tooltip /><Legend />
        {metric === 'savings' ? <Bar dataKey="savings" fill={colors[0]} /> : <>
          <Bar dataKey="income" fill={colors[0]} /><Bar dataKey="expenses" fill={colors[1]} />
        </>}
      </BarChart>}
    </ResponsiveContainer>
  </div></>;
}

export default function AssistantChat({ userId, sendQuestion, formatError }) {
  const storageKey = `smartspend_chat:${userId}`;
  const [messages, setMessages] = useState(() => loadMessages(storageKey));
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const history = useRef(null);
  const input = useRef(null);
  const request = useRef(null);
  const panel = useRef(null);

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    function resize() {
      const editor = input.current;
      panel.current?.style.setProperty('--chat-viewport', `${viewport.height}px`);
      if (editor && document.activeElement === editor) {
        const bounds = editor.getBoundingClientRect();
        if (bounds.bottom > viewport.offsetTop + viewport.height) editor.scrollIntoView({ block: 'nearest' });
      }
    }
    viewport.addEventListener('resize', resize);
    resize();
    return () => viewport.removeEventListener('resize', resize);
  }, []);
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(messages));
    } catch {
      // The conversation remains available in memory when browser storage is unavailable.
    }
    if (history.current) history.current.scrollTop = history.current.scrollHeight;
  }, [storageKey, messages, busy, error]);

  function clearConversation() {
    request.current?.abort();
    request.current = null;
    setBusy(false);
    setMessages([]);
    setQuestion('');
    setError('');
    input.current?.focus();
  }

  async function ask(event) {
    event.preventDefault();
    const text = question.trim();
    if (!text || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const previous = messages.filter(message => message.role === 'user').slice(-8).map(message => message.text);
    setMessages(current => [...current, { role: 'user', text, at: Date.now() }]);
    setQuestion('');
    setBusy(true);
    setError('');
    try {
      const data = await sendQuestion({ question: text, history: previous }, controller.signal);
      if (!controller.signal.aborted) {
        setMessages(current => [...current, { role: 'assistant', text: data.answer, display: data.display, at: Date.now() }]);
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        setMessages(current => current.slice(0, -1));
        setError(formatError(failure));
        setQuestion(current => current || text);
      }
    } finally {
      if (request.current === controller) {
        request.current = null;
        setBusy(false);
      }
    }
  }

  return <>
    <div className="assistant-prompts">
      {prompts.map(prompt => <button type="button" key={prompt} className="secondary-button" onClick={() => {
        setQuestion(prompt);
        input.current?.focus();
      }}>{prompt}</button>)}
    </div>
    <section className="panel assistant-panel" ref={panel}>
      <div className="chat-actions"><button type="button" className="secondary-button" disabled={!messages.length} onClick={clearConversation}>Clear conversation</button></div>
      <div className="chat-history" ref={history} role="log" aria-label="Conversation">
        {!messages.length && <p className="empty-state">Hi! I’m SmartSpend AI. Ask me a general question or look up your spending, income, and budgets.</p>}
        {messages.map((message, index) => <article className={`chat-message ${message.role}`} key={index}>
          <header><strong>{message.role === 'user' ? 'You' : 'SmartSpend'}</strong>
            <time dateTime={new Date(message.at).toISOString()}>{new Date(message.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
          </header>
          <p>{message.text}</p><FinanceDisplay display={message.display} />
        </article>)}
        {busy && <p role="status" className="subtitle">SmartSpend is typing…</p>}
      </div>
      {error && <p role="alert" className="page-error">{error}</p>}
      <form className="chat-form" onSubmit={ask}>
        <textarea ref={input} aria-label="Message" value={question} onChange={event => setQuestion(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form.requestSubmit();
            }
          }}
          rows={2} maxLength={1000} placeholder="Ask a question…" />
        <button type="submit" className="primary-button" disabled={busy || !question.trim()}>Send</button>
      </form>
    </section>
  </>;
}
