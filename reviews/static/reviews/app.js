/* ProfLens app js - kept CSP-clean (no inline) */
(function(){
  // school search filter on add-professor page
  var search = document.getElementById('school_search');
  var select = document.getElementById('id_school');
  if (search && select) {
    select.style.display = '';
    var opts = Array.from(select.options);
    function filter(){
      var q = search.value.toLowerCase();
      opts.forEach(function(o){
        o.hidden = !!(q && o.text.toLowerCase().indexOf(q) === -1);
      });
    }
    search.addEventListener('input', filter);
    select.addEventListener('change', function(){ search.value = select.options[select.selectedIndex].text; });
  }
  // language switch: submit on change (replaces inline onchange)
  var langSelect = document.querySelector('.lang-switch select[name="language"]');
  if (langSelect) {
    langSelect.addEventListener('change', function(){ this.form.submit(); });
  }
})();
