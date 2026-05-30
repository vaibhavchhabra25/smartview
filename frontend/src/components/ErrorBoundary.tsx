import { Component, ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { hasError: boolean; message: string }

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message }
  }

  handleReset = () => this.setState({ hasError: false, message: '' })

  render() {
    if (this.state.hasError) {
      return (
        <div className="container" style={{ textAlign: 'center', padding: '3rem' }}>
          <h2 style={{ color: '#ff4b2b' }}>Something went wrong</h2>
          <p style={{ color: 'rgba(255,255,255,0.6)', marginBottom: '1.5rem' }}>
            {this.state.message}
          </p>
          <button onClick={this.handleReset} style={{ maxWidth: 200, margin: '0 auto' }}>
            Try Again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
