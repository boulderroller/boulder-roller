import Header from '@/components/Header'
import Hero from '@/components/Hero'

export default function Home() {
  return (
    <div className="homepage">
      <Header />
      <main className="hero">
        <Hero />
      </main>
      <footer className="site-footer">
        <nav aria-label="Resources">
          <a href="https://docs.boulderroller.xyz/">Docs</a>
          <span className="footer-separator" aria-hidden="true">·</span>
          <a href="https://docs.boulderroller.xyz/reference/faq">FAQ</a>
        </nav>
      </footer>
    </div>
  )
}
