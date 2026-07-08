// 원문 즉시보기 모달 - 버튼 클릭 시 iframe으로 원문(식약처 링크 또는 업로드 파일)을 바로 띄웁니다.
// iframe이 차단되는 사이트일 경우를 대비해 "새 창에서 열기" 링크를 항상 함께 표시합니다.
(function () {
  const modal = document.getElementById("doc-modal");
  if (!modal) return;

  const iframe = document.getElementById("doc-modal-iframe");
  const titleEl = document.getElementById("doc-modal-title");
  const newTabLink = document.getElementById("doc-modal-newtab");

  function openModal(title, url) {
    titleEl.textContent = title || "원문 보기";
    newTabLink.href = url;
    iframe.src = url;
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    modal.hidden = true;
    iframe.src = "about:blank";
    document.body.style.overflow = "";
  }

  document.addEventListener("click", function (e) {
    const btn = e.target.closest(".btn-view-original");
    if (btn) {
      e.preventDefault();
      openModal(btn.dataset.title, btn.dataset.url);
      return;
    }
    if (e.target.closest("[data-modal-close]")) {
      closeModal();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });
})();
