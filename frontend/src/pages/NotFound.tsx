import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="error-page">
      <div>
        <span className="eyebrow">404</span>
        <h1>Page not found</h1>
        <p className="muted">The page you are looking for does not exist or has moved.</p>
        <Link className="button primary" to="/">Back to the builder</Link>
      </div>
    </div>
  )
}
