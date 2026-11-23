// Small enhancements for the static guide. The page works without this script.
(function () {
  "use strict";

  // Highlight the contents link for the section currently in view.
  var links = Array.prototype.slice.call(document.querySelectorAll(".contents a[href^='#']"));
  var byId = {};
  links.forEach(function (link) {
    byId[link.getAttribute("href").slice(1)] = link;
  });

  if ("IntersectionObserver" in window && links.length) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          links.forEach(function (link) { link.classList.remove("active"); });
          var link = byId[entry.target.id];
          if (link) link.classList.add("active");
        });
      },
      { rootMargin: "-30% 0px -60% 0px" }
    );
    document.querySelectorAll("section[id]").forEach(function (section) {
      observer.observe(section);
    });
  }

  // Add a copy button to every code block.
  document.querySelectorAll("pre").forEach(function (block) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "copy";
    button.textContent = "Copy";
    button.addEventListener("click", function () {
      var text = block.querySelector("code") ? block.querySelector("code").innerText : block.innerText;
      var done = function () {
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = "Copy"; }, 1500);
      };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(done, function () {});
      }
    });
    block.appendChild(button);
  });
})();
