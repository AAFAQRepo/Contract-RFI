import { Link, useNavigate } from 'react-router-dom'
import { Logo, Icon } from '../components/common/Icon'

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <div className="landing-container">
      {/* Navigation */}
      <nav className="landing-nav">
        <div className="nav-left">
          <Logo />
          <span className="logo-text">Contract RFI</span>
        </div>
        <div className="nav-center">
          <a href="#product">Product <Icon.ChevronDown /></a>
          <a href="#resources">Resources <Icon.ChevronDown /></a>
          <a href="#customers">Customers</a>
          <a href="#careers">Careers</a>
          <a href="#security">Security</a>
        </div>
        <div className="nav-right">
          <button onClick={() => navigate('/login')} className="nav-link-btn">Login</button>
          <button onClick={() => navigate('/register')} className="btn-white">Book a Demo</button>
        </div>
      </nav>

      {/* Hero Section */}
      <header className="hero">
        <div className="pill">Scale your contract flow with AI</div>
        <h1 className="hero-title">Better deals, faster.</h1>
        <p className="hero-subtitle">
          Contract RFI is the complete AI suite for contracts: review,
          automate workflows and surface insights from your deal history.
        </p>
        <div className="hero-actions">
          <button className="btn-orange">Book a Demo</button>
          <Link to="/register" className="btn-white">Try it Free</Link>
        </div>
      </header>

      {/* Features Grid */}
      <section className="features-section" id="product">
        <h2 className="section-title">Scale your contract flow <br/>responsibly with AI</h2>
        <p className="section-subtitle">Contract RFI uses legal AI to streamline the drafting, <br/>redlining, and review of contracts directly in your browser.</p>
        
        <div className="features-grid">
          <FeatureCard 
            title="Review" 
            desc="Redline contracts and catch risks" 
            icon={<div className="f-icon orange"><Icon.Collapse /></div>}
          />
          <FeatureCard 
            title="Draft" 
            desc="Draft from scratch or past precedents" 
            icon={<div className="f-icon green"><Icon.Plus /></div>}
          />
          <FeatureCard 
            title="Ask" 
            desc="Accurate answers, with citations" 
            icon={<div className="f-icon blue"><Icon.Search /></div>}
          />
          <FeatureCard 
            title="Benchmarks" 
            desc="Compare contracts to industry standards" 
            icon={<div className="f-icon yellow"><Icon.Workflows /></div>}
          />
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="footer-content">
          <div className="footer-brand">
            <p>Contract RFI is the most complete AI suite for commercial legal work, trusted by more than 4,000 in-house teams and law firms worldwide.</p>
            <div className="social-links">
               {/* Icons would go here */}
            </div>
          </div>
          <div className="footer-links-grid">
            <div className="footer-col">
              <h4>Product</h4>
              <a href="#">Review</a>
              <a href="#">Draft</a>
              <a href="#">Ask</a>
            </div>
            <div className="footer-col">
              <h4>Resources</h4>
              <a href="#">Blog</a>
              <a href="#">Help Center</a>
              <a href="#">Security</a>
            </div>
            <div className="footer-col">
              <h4>Company</h4>
              <a href="#">About</a>
              <a href="#">Careers</a>
              <a href="#">Contact</a>
            </div>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© 2026 Contract RFI</span>
          <div className="legal-links">
            <a href="#">Privacy Policy</a>
            <a href="#">Terms of Service</a>
          </div>
        </div>
      </footer>
    </div>
  )
}

function FeatureCard({ title, desc, icon }) {
  return (
    <div className="feature-card">
      <div className="feature-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{desc}</p>
    </div>
  )
}
