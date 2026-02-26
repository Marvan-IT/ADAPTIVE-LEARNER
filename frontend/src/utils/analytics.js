import posthog from "posthog-js";

let initialized = false;

export function initPostHog() {
  const key = import.meta.env.VITE_POSTHOG_KEY;
  const host = import.meta.env.VITE_POSTHOG_HOST;
  if (!key) return;

  posthog.init(key, {
    api_host: host || "https://us.i.posthog.com",
    capture_pageview: false, // we handle this manually with React Router
    capture_pageleave: true,
    autocapture: false,
  });
  initialized = true;
}

export function identifyStudent(student) {
  if (!initialized || !student) return;
  posthog.identify(String(student.id), {
    name: student.display_name,
    language: student.preferred_language,
    interests: student.interests,
    preferred_style: student.preferred_style,
  });
}

export function trackEvent(event, properties = {}) {
  if (!initialized) return;
  posthog.capture(event, properties);
}

export function trackPageView(path) {
  if (!initialized) return;
  posthog.capture("$pageview", { $current_url: path });
}

export function resetUser() {
  if (!initialized) return;
  posthog.reset();
}
