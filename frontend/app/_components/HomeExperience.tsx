"use client";

import Link from "next/link";

import { useHomeMotion } from "../_lib/use-home-motion";
const VIDEO_URL = "/gameweave/homepage/hero-scroll.mp4";

export function HomeExperience() {
  useHomeMotion(VIDEO_URL);

  return (
    <div className="fp-home">
      <div id="scroll-video-container" aria-hidden="true">
        <canvas id="video-canvas" />
        <video id="video-fallback" muted playsInline preload="auto" crossOrigin="anonymous" src={VIDEO_URL} />
        <div className="overlay" />
      </div>

      <canvas id="particles-canvas" aria-hidden="true" />

      <div id="fixed-cards" aria-hidden="true">
        <div className="grid">
          <div className="card">
            <h3>Explore community games</h3>
            <p>
              Browse playable worlds from creators, remix the ideas you love, and jump into web games
              instantly from the GameWeave library.
            </p>
          </div>
          <div className="card">
            <h3>Generate with AI agents</h3>
            <p>
              Turn plain-language prompts and uploaded assets into complete game loops, packaged files,
              and publish-ready previews.
            </p>
          </div>
          <div className="card">
            <h3>Publish in the browser</h3>
            <p>
              Share games without installs, track creation tasks, and keep every playable build close to
              your creator workspace.
            </p>
          </div>
        </div>
      </div>

      <nav className="fp-home-nav" aria-label="Home navigation">
        <div className="nav-left">
          <Link href="/" className="logo">
            GameWeave AI
          </Link>
          <div className="nav-links">
            <Link href="/explore">Explore</Link>
            <Link href="/create">Create</Link>
            <Link href="/explore#how">How it works</Link>
          </div>
        </div>
        <div className="social">
          <Link href="/login">Log in</Link>
          <Link href="/about" aria-label="About GameWeave">
            <svg fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 2 3.5 6.8v10.4L12 22l8.5-4.8V6.8L12 2Zm0 2.3 6.5 3.7L12 11.7 5.5 8 12 4.3Zm-6.5 6 5.5 3.1v5.7l-5.5-3.1v-5.7Zm7.5 8.8v-5.7l5.5-3.1V16L13 19.1Z" />
            </svg>
          </Link>
        </div>
      </nav>

      <main id="content">
        <section id="hero">
          <div className="gradient-overlay" />
          <div className="content">
            <p className="subtitle">GAMEWEAVE AI</p>
            <h1>
              Instantly craft playable{" "}
              <span className="underlined">
                <span className="line" />
                <span>AI games</span>
              </span>{" "}
              on the web.
            </h1>
            <div className="ctas">
              <Link href="/explore" className="cta-btn">
                Get Started <span aria-hidden="true">-&gt;</span>
              </Link>
            </div>
          </div>
          <div className="bounce-arrow" aria-hidden="true">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="2" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          </div>
        </section>

        <div className="spacer spacer-large" />
        <div id="cards-trigger" />
        <div className="spacer spacer-medium" />

        <section id="section-three">
          <div className="inner" id="section-three-inner">
            <p>Enter the arcade</p>
            <h2>Play, create, publish</h2>
            <Link href="/explore" className="section-link">
              Open Explore
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}
