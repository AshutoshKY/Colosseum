import { Component, type PropsWithChildren } from 'react'

interface State { error?: Error }

export class ErrorBoundary extends Component<PropsWithChildren, State> {
  state: State = {}

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="error-page">
        <div>
          <h1>Something went wrong</h1>
          <p className="muted">{this.state.error.message}</p>
          <button className="primary" onClick={() => { this.setState({ error: undefined }); window.location.assign('/') }}>
            Back to home
          </button>
        </div>
      </div>
    )
  }
}
