(function () {
    var storedTheme = localStorage.getItem('boma-theme') || 'light';
    document.documentElement.dataset.theme = storedTheme;

    document.addEventListener('DOMContentLoaded', function () {
        var selector = document.querySelector('[data-theme-selector]');
        if (!selector) return;
        selector.value = document.documentElement.dataset.theme;
        selector.addEventListener('change', function () {
            document.documentElement.dataset.theme = selector.value;
            localStorage.setItem('boma-theme', selector.value);
        });
    });
})();
