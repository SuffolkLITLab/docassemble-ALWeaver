<%def name="preview_field(field)">\
        <div class="row">
            <div class="col-sm">
            ${ field.label }
            </div>
            <div class="col-sm">
            [--------------]
            </div>
        </div>
</%def>
<%def name="preview_question_screen(question)">\
<div class="card">
  <div class="card-header">
    ${ question.question_text }
  </div>
  <div class="card-body">
    <h5 class="card-title">${ question.subquestion_text }</h5>
    <div class="container">
    % for field in question.field_list:
    ${ preview_field(field) }
    % endfor
    </div>
    <a href="#" class="btn btn-primary">Go somewhere</a>
  </div>
</div>
</%def>