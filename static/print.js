// Opens the browser print dialog for the summary page; "Save as PDF" produces the PDF file.
window.addEventListener('load', () => { if (new URLSearchParams(location.search).get('auto') !== '0') window.print(); });
