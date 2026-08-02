"use client";

import { useEffect } from "react";

export function useHomeMotion(videoUrl: string) {
  useEffect(() => {
    let cancelled = false;
    const cleanupCallbacks: Array<() => void> = [];

    const videoCanvas = document.getElementById("video-canvas");
    const videoEl = document.getElementById("video-fallback");
    const particlesCanvas = document.getElementById("particles-canvas");
    const hero = document.getElementById("hero");
    const fixedCards = document.getElementById("fixed-cards");
    const trigger = document.getElementById("cards-trigger");
    const sectionThreeInner = document.getElementById("section-three-inner");

    if (
      !(videoCanvas instanceof HTMLCanvasElement) ||
      !(videoEl instanceof HTMLVideoElement) ||
      !(particlesCanvas instanceof HTMLCanvasElement) ||
      !(hero instanceof HTMLElement) ||
      !(fixedCards instanceof HTMLElement) ||
      !(trigger instanceof HTMLElement) ||
      !(sectionThreeInner instanceof HTMLElement)
    ) {
      return;
    }

    const videoCanvasEl = videoCanvas;
    const videoFallbackEl = videoEl;
    const particlesCanvasEl = particlesCanvas;
    const heroEl = hero;
    const fixedCardsEl = fixedCards;
    const triggerEl = trigger;
    const sectionThreeInnerEl = sectionThreeInner;

    const videoContext = videoCanvasEl.getContext("2d");
    const particlesContext = particlesCanvasEl.getContext("2d");
    const cardsGrid = fixedCardsEl.querySelector(".grid");

    if (
      !videoContext ||
      !particlesContext ||
      !(cardsGrid instanceof HTMLElement)
    ) {
      return;
    }

    const videoCtx = videoContext;
    const particlesCtx = particlesContext;
    const cardsGridEl = cardsGrid;
    const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const constrainedViewportQuery = window.matchMedia("(max-width: 768px), (hover: none), (pointer: coarse)");
    const shouldReduceMotion = () => reducedMotionQuery.matches;
    const shouldConserveResources = () => constrainedViewportQuery.matches;
    const shouldAnimateParticles = () => !shouldReduceMotion() && !shouldConserveResources() && !document.hidden;

    let frames: ImageBitmap[] = [];
    let framesReady = false;
    let lastFrameIndex = -1;
    let videoSeeking = false;
    let extractingFrames = false;
    let videoFrameRequest = 0;
    let cardsFrameRequest = 0;
    let particlesFrameRequest = 0;

    function releaseFrames() {
      frames.forEach((frame) => frame.close());
      frames = [];
      framesReady = false;
      lastFrameIndex = -1;
    }

    function resizeVideoCanvas() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = videoCanvasEl.getBoundingClientRect();
      const width = Math.round(rect.width * dpr);
      const height = Math.round(rect.height * dpr);

      if (videoCanvasEl.width !== width || videoCanvasEl.height !== height) {
        videoCanvasEl.width = width;
        videoCanvasEl.height = height;
      }

      lastFrameIndex = -1;
    }

    async function extractFrames() {
      if (shouldReduceMotion() || shouldConserveResources() || extractingFrames || !("createImageBitmap" in window)) return;

      let objectUrl: string | undefined;
      const capturedFrames: ImageBitmap[] = [];
      extractingFrames = true;

      try {
        const response = await fetch(videoUrl, { mode: "cors" });
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);

        const video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.crossOrigin = "anonymous";
        video.preload = "auto";
        video.src = objectUrl;

        await new Promise<void>((resolve, reject) => {
          video.onloadedmetadata = () => resolve();
          video.onerror = () => reject(new Error("Video metadata failed to load"));
          window.setTimeout(() => reject(new Error("Video metadata timed out")), 15000);
        });

        const scale = Math.min(1, 1280 / video.videoWidth);
        const scaledWidth = Math.round(video.videoWidth * scale);
        const scaledHeight = Math.round(video.videoHeight * scale);
        const frameCount = Math.max(30, Math.min(72, Math.round(video.duration * 18)));

        for (let index = 0; index < frameCount && !cancelled; index += 1) {
          const time = (index / (frameCount - 1)) * (video.duration - 0.05);
          video.currentTime = time;

          await new Promise<void>((resolve, reject) => {
            const timeout = window.setTimeout(() => {
              video.removeEventListener("seeked", onSeeked);
              reject(new Error("Frame seek timed out"));
            }, 3000);

            function onSeeked() {
              window.clearTimeout(timeout);
              video.removeEventListener("seeked", onSeeked);
              resolve();
            }

            video.addEventListener("seeked", onSeeked);
          });

          const bitmap = await createImageBitmap(video, {
            resizeWidth: scaledWidth,
            resizeHeight: scaledHeight,
          });

          capturedFrames.push(bitmap);
        }

        if (cancelled || shouldReduceMotion() || shouldConserveResources()) {
          capturedFrames.forEach((frame) => frame.close());
          return;
        }

        if (!cancelled && capturedFrames.length > 0) {
          releaseFrames();
          frames = capturedFrames;
          framesReady = true;
          videoCanvasEl.style.visibility = "visible";
          videoFallbackEl.style.display = "none";
          requestVideoFrame();
        }
      } catch {
        capturedFrames.forEach((frame) => frame.close());
        videoCanvasEl.style.visibility = "hidden";
        videoFallbackEl.style.display = "block";
      } finally {
        extractingFrames = false;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      }
    }

    function getScrollBounds() {
      const viewportHeight = window.innerHeight;

      return {
        start: viewportHeight * 0.5,
        end: document.documentElement.scrollHeight - viewportHeight,
      };
    }

    function getVideoProgress() {
      const { start, end } = getScrollBounds();
      const range = end - start;

      if (range <= 0) return 0;

      return Math.max(0, Math.min(1, (window.scrollY - start) / range));
    }

    function drawFrame(frame: ImageBitmap) {
      const canvasWidth = videoCanvasEl.width;
      const canvasHeight = videoCanvasEl.height;
      const scale = Math.max(canvasWidth / frame.width, canvasHeight / frame.height);
      const drawWidth = frame.width * scale;
      const drawHeight = frame.height * scale;

      videoCtx.drawImage(
        frame,
        (canvasWidth - drawWidth) / 2,
        (canvasHeight - drawHeight) / 2,
        drawWidth,
        drawHeight,
      );
    }

    function drawVideoForScroll() {
      if (cancelled || shouldReduceMotion()) return;

      const progress = getVideoProgress();

      if (framesReady && frames.length > 0) {
        const index = Math.round(progress * (frames.length - 1));

        if (index !== lastFrameIndex) {
          lastFrameIndex = index;
          const frame = frames[index];
          if (frame) drawFrame(frame);
        }
      } else if (videoFallbackEl.duration && Number.isFinite(videoFallbackEl.duration) && videoFallbackEl.readyState >= 1) {
        const target = progress * videoFallbackEl.duration;

        if (!videoSeeking && Math.abs(videoFallbackEl.currentTime - target) > 0.001) {
          videoSeeking = true;

          try {
            videoFallbackEl.currentTime = target;
          } catch {
            videoSeeking = false;
          }
        }
      }
    }

    function requestVideoFrame() {
      if (cancelled || shouldReduceMotion() || videoFrameRequest) return;
      videoFrameRequest = window.requestAnimationFrame(() => {
        videoFrameRequest = 0;
        drawVideoForScroll();
      });
    }

    type Particle = {
      x: number;
      y: number;
      vx: number;
      vy: number;
      size: number;
      opacity: number;
    };

    let particles: Particle[] = [];

    function createParticles() {
      particles = [];
      if (!shouldAnimateParticles()) return;

      const count = Math.floor((particlesCanvasEl.width * particlesCanvasEl.height) / 12000);

      for (let index = 0; index < count; index += 1) {
        particles.push({
          x: Math.random() * particlesCanvasEl.width,
          y: Math.random() * particlesCanvasEl.height,
          vx: (Math.random() - 0.5) * 0.3,
          vy: (Math.random() - 0.5) * 0.3,
          size: Math.random() * 1.5 + 0.5,
          opacity: Math.random() * 0.6 + 0.2,
        });
      }
    }

    function resizeParticles() {
      particlesCanvasEl.width = window.innerWidth;
      particlesCanvasEl.height = window.innerHeight;
      createParticles();
      if (!shouldAnimateParticles()) {
        particlesCtx.clearRect(0, 0, particlesCanvasEl.width, particlesCanvasEl.height);
      }
    }

    function animateParticles() {
      particlesFrameRequest = 0;
      if (cancelled || !shouldAnimateParticles()) return;

      particlesCtx.clearRect(0, 0, particlesCanvasEl.width, particlesCanvasEl.height);

      for (const particle of particles) {
        particle.x += particle.vx;
        particle.y += particle.vy;

        if (particle.x < 0) particle.x = particlesCanvasEl.width;
        if (particle.x > particlesCanvasEl.width) particle.x = 0;
        if (particle.y < 0) particle.y = particlesCanvasEl.height;
        if (particle.y > particlesCanvasEl.height) particle.y = 0;

        particlesCtx.beginPath();
        particlesCtx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
        particlesCtx.fillStyle = `rgba(255,255,255,${particle.opacity})`;
        particlesCtx.fill();
      }

      particlesFrameRequest = window.requestAnimationFrame(animateParticles);
    }

    function startParticles() {
      if (particlesFrameRequest || !shouldAnimateParticles()) return;
      particlesFrameRequest = window.requestAnimationFrame(animateParticles);
    }

    function stopParticles() {
      if (particlesFrameRequest) {
        window.cancelAnimationFrame(particlesFrameRequest);
        particlesFrameRequest = 0;
      }
      particlesCtx.clearRect(0, 0, particlesCanvasEl.width, particlesCanvasEl.height);
    }

    function updateHeroOpacity() {
      const fade = Math.max(0, 1 - window.scrollY / (window.innerHeight * 0.3));
      heroEl.style.opacity = String(fade);
    }

    function updateCards() {
      cardsFrameRequest = 0;
      if (cancelled) return;

      const rect = triggerEl.getBoundingClientRect();
      const triggerTop = rect.top + window.scrollY;
      const triggerHeight = rect.height;
      const scrollY = window.scrollY;
      const viewportHeight = window.innerHeight;
      const start = triggerTop - viewportHeight * 0.5;
      const end = triggerTop + triggerHeight - viewportHeight * 0.3;
      const range = end - start;
      const rawProgress = range > 0 ? (scrollY - start) / range : 0;
      const progress = Math.max(0, Math.min(1, rawProgress));
      const isActive = scrollY >= start - viewportHeight * 0.2 && scrollY <= end + viewportHeight * 0.3;
      const fadeIn = Math.min(1, Math.max(0, (scrollY - (start - viewportHeight * 0.2)) / (viewportHeight * 0.2)));
      const fadeOut = Math.min(1, Math.max(0, (end + viewportHeight * 0.3 - scrollY) / (viewportHeight * 0.3)));
      const containerOpacity = isActive ? Math.min(fadeIn, fadeOut) : 0;
      const isMobile = window.innerWidth < 768;
      const revealPercent = progress * 130;
      const mask = isMobile
        ? `linear-gradient(to bottom, black ${revealPercent}%, transparent ${revealPercent + 20}%)`
        : `linear-gradient(to right, black ${revealPercent}%, transparent ${revealPercent + 15}%)`;

      fixedCardsEl.style.opacity = String(containerOpacity);
      fixedCardsEl.style.pointerEvents = containerOpacity > 0.1 ? "auto" : "none";
      cardsGridEl.style.maskImage = mask;
      cardsGridEl.style.setProperty("-webkit-mask-image", mask);
    }

    function requestCardsFrame() {
      if (cancelled || cardsFrameRequest) return;
      cardsFrameRequest = window.requestAnimationFrame(updateCards);
    }

    const handleScroll = () => {
      updateHeroOpacity();
      requestVideoFrame();
      requestCardsFrame();
    };

    const handleResize = () => {
      resizeVideoCanvas();
      resizeParticles();
      requestVideoFrame();
      requestCardsFrame();
      startParticles();
    };

    const handleResourcePreferenceChange = () => {
      if (shouldReduceMotion() || shouldConserveResources()) {
        releaseFrames();
        stopParticles();
        videoCanvasEl.style.visibility = "hidden";
        videoFallbackEl.style.display = "block";
      } else {
        void extractFrames();
        startParticles();
      }
      requestVideoFrame();
      requestCardsFrame();
    };

    const handleVisibilityChange = () => {
      if (document.hidden) {
        stopParticles();
      } else {
        startParticles();
      }
    }

    const handleVideoSeeked = () => {
      videoSeeking = false;
      requestVideoFrame();
    };

    const handleVideoLoaded = () => {
      try {
        videoFallbackEl.currentTime = 0;
      } catch {
        videoSeeking = false;
      }
      requestVideoFrame();
    };

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          sectionThreeInnerEl.classList.add("visible");
          observer.unobserve(sectionThreeInnerEl);
        }
      },
      { threshold: 0.15 },
    );

    resizeVideoCanvas();
    resizeParticles();
    videoCanvasEl.style.visibility = "hidden";
    if (shouldReduceMotion()) {
      videoFallbackEl.style.display = "block";
    } else {
      void extractFrames();
    }
    updateHeroOpacity();
    requestVideoFrame();
    requestCardsFrame();
    startParticles();

    window.addEventListener("resize", handleResize);
    window.addEventListener("scroll", handleScroll, { passive: true });
    document.addEventListener("visibilitychange", handleVisibilityChange);
    reducedMotionQuery.addEventListener("change", handleResourcePreferenceChange);
    constrainedViewportQuery.addEventListener("change", handleResourcePreferenceChange);
    videoFallbackEl.addEventListener("seeked", handleVideoSeeked);
    videoFallbackEl.addEventListener("stalled", handleVideoSeeked);
    videoFallbackEl.addEventListener("loadeddata", handleVideoLoaded);
    observer.observe(sectionThreeInnerEl);

    cleanupCallbacks.push(
      () => window.removeEventListener("resize", handleResize),
      () => window.removeEventListener("scroll", handleScroll),
      () => document.removeEventListener("visibilitychange", handleVisibilityChange),
      () => reducedMotionQuery.removeEventListener("change", handleResourcePreferenceChange),
      () => constrainedViewportQuery.removeEventListener("change", handleResourcePreferenceChange),
      () => videoFallbackEl.removeEventListener("seeked", handleVideoSeeked),
      () => videoFallbackEl.removeEventListener("stalled", handleVideoSeeked),
      () => videoFallbackEl.removeEventListener("loadeddata", handleVideoLoaded),
      () => observer.disconnect(),
      () => {
        if (videoFrameRequest) window.cancelAnimationFrame(videoFrameRequest);
        if (cardsFrameRequest) window.cancelAnimationFrame(cardsFrameRequest);
        stopParticles();
        releaseFrames();
      },
    );

    return () => {
      cancelled = true;
      cleanupCallbacks.forEach((cleanup) => cleanup());
    };
  }, [videoUrl]);
}
