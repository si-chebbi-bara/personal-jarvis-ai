import { useState } from 'react'

// Shown instead of the app until a token is saved. The token is the
// JARVIS_API_TOKEN value from the backend's .env file.
function TokenGate({ rejected, onSubmit }) {
  const [value, setValue] = useState('')

  function submit(e) {
    e.preventDefault()
    if (value.trim()) onSubmit(value.trim())
  }

  return (
    <div className="token-gate">
      <form className="token-card" onSubmit={submit}>
        <h1>Unlock Jarvis</h1>
        <p>
          Paste the <code>JARVIS_API_TOKEN</code> from the backend&rsquo;s{' '}
          <code>.env</code> file. It is saved in this browser only.
        </p>
        {rejected && (
          <p className="token-error" role="alert">
            The backend rejected that token. Check it and try again.
          </p>
        )}
        <input
          type="password"
          autoComplete="off"
          autoFocus
          placeholder="Jarvis API token"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button type="submit" disabled={!value.trim()}>
          Unlock
        </button>
      </form>
    </div>
  )
}

export default TokenGate
