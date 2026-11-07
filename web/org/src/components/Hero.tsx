import ClimbExplorer from './ClimbExplorer'

export default function Hero() {
  return (
    <ClimbExplorer>
      <div className="introduction">
        <h1 aria-label="Boulder Roller">
          <span>Boulder</span>
          <span>Roller</span>
        </h1>
        <p>
          A cycling app with leaderboards that pay riders in DUNG.
        </p>
        <span className="coming-soon" role="status">
          <span className="status-dot" aria-hidden="true" />
          Coming soon
        </span>
        <a className="docs-button" href="https://docs.boulderroller.xyz/">
          Read the docs
          <span className="docs-button-arrow" aria-hidden="true">→</span>
        </a>
      </div>
    </ClimbExplorer>
  )
}
