import { createContext, useCallback, useContext, useReducer } from 'react'

const ToastContext = createContext(null)

function reducer(state, action) {
  switch (action.type) {
    case 'ADD':
      return [...state, { id: action.id, message: action.message, variant: action.variant }]
    case 'REMOVE':
      return state.filter(t => t.id !== action.id)
    default:
      return state
  }
}

const VARIANTS = {
  error: { background: '#c62828', color: '#fff' },
  info:  { background: '#1565c0', color: '#fff' },
}

export function ToastProvider({ children }) {
  const [toasts, dispatch] = useReducer(reducer, [])

  const showToast = useCallback((message, variant = 'info') => {
    const id = Date.now() + Math.random()
    dispatch({ type: 'ADD', id, message, variant })
    setTimeout(() => dispatch({ type: 'REMOVE', id }), 4000)
  }, [])

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div style={{ position: 'fixed', top: '1rem', right: '1rem', zIndex: 9999, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {toasts.map(t => (
          <div key={t.id} style={{ ...VARIANTS[t.variant] || VARIANTS.info, padding: '0.75rem 1rem', borderRadius: '4px', maxWidth: '320px', display: 'flex', alignItems: 'center', gap: '0.75rem', boxShadow: '0 2px 8px rgba(0,0,0,0.3)' }}>
            <span style={{ flex: 1, fontSize: '0.9rem' }}>{t.message}</span>
            <button onClick={() => dispatch({ type: 'REMOVE', id: t.id })} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1rem', lineHeight: 1 }}>×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
