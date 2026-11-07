// Source for js/vendor/orbs.bundle.js. Rebuild with react@18.3.1, react-dom@18.3.1, thinking-orbs@0.3.2:
// npx esbuild orbs.js --bundle --minify --format=iife --define:process.env.NODE_ENV='"production"' --outfile=vendor/orbs.bundle.js
import React from "react";
import { createRoot } from "react-dom/client";
import { ThinkingOrb } from "thinking-orbs";

const roots = new WeakMap();

function isDark() {
    return !document.body.classList.contains("light-theme");
}

function render(el) {
    if (!el.isConnected) return;
    let root = roots.get(el);
    if (!root) {
        root = createRoot(el);
        roots.set(el, root);
    }
    const size = Number(el.dataset.orbSize) === 20 ? 20 : 64;
    root.render(React.createElement(ThinkingOrb, {
        state: el.dataset.orb || "working",
        size,
        dark: isDark(),
        speed: Number(el.dataset.orbSpeed) || 1,
    }));
}

function mountAll(scope = document) {
    if (scope.matches && scope.matches("[data-orb]")) render(scope);
    scope.querySelectorAll?.("[data-orb]").forEach(render);
}

new MutationObserver((mutations) => {
    for (const m of mutations) {
        if (m.type === "attributes") {
            if (m.target === document.body) mountAll();
            else if (m.attributeName === "data-orb") render(m.target);
        } else {
            m.addedNodes.forEach((n) => n.nodeType === 1 && mountAll(n));
        }
    }
}).observe(document.body, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["data-orb", "class"],
});

mountAll();
