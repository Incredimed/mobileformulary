"""
OpenBNF
"""
import difflib
import functools
import json
import os
import re

from flask import Flask, abort, request, redirect, Response, make_response
from flask import render_template
import jinja2
from jinja2 import evalcontextfilter, Markup, escape

from db import db

app = Flask(__name__)
app.debug = True

NAMES = [d['name'] for d in db.drugs.find()]

def include_file(name):
    return jinja2.Markup(loader.get_source(env, name)[0])

loader = jinja2.PackageLoader(__name__, 'templates')
env = jinja2.Environment(loader=loader)
env.globals['include_file'] = include_file

"""
Filters - Turn Newlines into<br> please
Kudos http://flask.pocoo.org/snippets/28/
"""
_paragraph_re = re.compile(r'(?:\r\n|\r|\n){2,}')

@app.template_filter()
@evalcontextfilter
def nl2br(eval_ctx, value):
    result = u'\n\n'.join(u'<p>%s</p>' % p.replace('\n', '<br>\n') \
        for p in _paragraph_re.split(escape(value)))
    if eval_ctx.autoescape:
        result = Markup(result)
    return result

def json_template(tplname, **context):
    return Response(
        render_template(tplname,**context),
        mimetype='application/json'
        )

def without_oid(fn):
    def wrapper(*args, **kwargs):
        results = fn(*args, **kwargs)
        for i in range(len(results)):
            del results[i]['_id']
        return results
    return wrapper

def jsonp(fn):
    @functools.wraps(fn)
    def with_callback_maybe(*args,**kwargs):
        results = fn(*args,**kwargs)
        results = json.dumps(results)
        if  request.args.get('callback', None):
            return '{0}({1})'.format(request.args.get('callback'), results)
        else:
            return Response(results, mimetype='application/json')
    return with_callback_maybe

"""
Search
"""
@without_oid
def drugs_like_me(term):
    """
    Return a list of Drugs that are like our search term.
    (For some value of like)
    """
    splitter = None
    for splittee in ['|', ' OR ']:
        if term.find(splittee) != -1:
            splitter = splittee
            break

    if splitter:
        results = []
        frist, rest = term.split(splitter, 1)
        results = drugs_like_me(frist)
        results += drugs_like_me(rest);
        return results

    return [d for d in db.drugs.find({'name': {'$regex': term, '$options':'i'}})]

def drugs_quite_close(drug):
    """
    There are no exact matches for DRUG, but we can
    do better than just bailing.

    Perform a fuzzy match and return that.
    """
    wholeterm = difflib.get_close_matches(drug.upper(), NAMES)
    fristword = difflib.get_close_matches(drug.split()[0].upper(), NAMES)
    print 'wholeterm', wholeterm
    print 'fristword', fristword
    return list(set(wholeterm + fristword))

"""
Views
"""
@app.route("/")
def index():
    return render_template('index.html')

@app.route("/about")
def about():
    return render_template('about.html')

@app.route("/search", methods = ['GET', 'POST'])
def search():
    if request.method == 'POST':
        drug = request.form.get('q', '')
    else:
        drug = request.args.get('q', '')

    print 'Query is ', drug

    results = drugs_like_me(drug)

    if len(results) == 1 and results[0]['name'].lower() == drug.lower():
        return redirect('/result/{0}'.format(results[0]['name']))
    suggestions = []
    if not results:
        suggestions = drugs_quite_close(drug)
    return render_template('search.jinja2', results=results, query=drug, suggestions=suggestions)

@app.route("/result/<drug>")
def result(drug):

    drug = db.drugs.find_one({'name': drug})

    del drug['_id']
    whitelist = ['doses', 'contra-indications', 'interactions', 'name', 'breadcrumbs', 'fname']
    impairments = [k for k in drug if k.find('impairment')!= -1]
    whitelist += impairments
    return render_template('result.html', drug=drug,
                           whitelist=whitelist, impairments=impairments)

@app.route('/jstesting')
def jstesting():
    return env.get_template('jstest.html').render()

@app.route('/ajaxsearch', methods = ['GET'])
def ajaxsearch():
    term = request.args.get('term')
    term = term.replace('+',  ' ')
    responses = drugs_like_me(term)[:10]
    responses = [n['name'] for n in responses]
    if len(responses) > 0:
        return json.dumps(responses)
    return json.dumps(drugs_quite_close(term))

@app.route('/api/')
def api_v1_drugs():
    term = request.args.get('drug')
    names = drugs_like_me(term)
    results = [bnf[n] for n in names]
    if  request.args.get('callback', None):
        return '{0}({1})'.format(request.args.get('callback'), json.dumps(results))
    else:
        return Response(json.dumps(results), mimetype='application/json')

@app.route('/api/v2/openbnf')
def apidoc_endpoint():
    return json_template('api/base.json.js', host=request.host)

@app.route('/api/v2/openbnf/drug')
def apidoc_drug_endpoint():
    return json_template('api/drug.json.js', host=request.host)

@app.route('/api/v2/openbnf/indication')
def apidoc_indication_endpoint():
    return json_template('api/indication.json.js', host=request.host)

@app.route('/api/v2/openbnf/sideeffects')
def apidoc_sideeffects_endpoint():
    return json_template('api/sideeffects.json.js', host=request.host)

@app.route('/api/v2/doc')
def apidoc():
    return env.get_template('apidoc.html').render()

@app.route('/api/v2/drug/<code>')
@jsonp
def api_v2_drug_bnf_code(code):
    codemap = db.codes.find_one({'code': code})
    if not codemap:
        abort(404)
    drug = db.drugs.find_one({'name': codemap['name']})
    if not drug:
        abort(404)
    del drug['_id']
    return drug

@app.route('/api/v2/drug')
@jsonp
def api_v2_drug():
    term = request.args.get('name')
    return drugs_like_me(term)

@app.route('/api/v2/indication')
@jsonp
def api_v2_indication():
    term = request.args.get('indication')
    resultz = [d for d in db.drugs.find({'indications': {'$regex': term, '$options':'i'}})]
    if not resultz:
        abort(404)
    for i in range(len(resultz)):
        del resultz[i]['_id']
    return resultz

@app.route('/api/v2/sideeffects')
@jsonp
def api_v2_sideeffects():
    term = request.args.get('sideeffects')
    resultz = [d for d in db.drugs.find({'side-effects': {'$regex': term, '$options':'i'}})]
    if not resultz:
        abort(404)
    for i in range(len(resultz)):
        del resultz[i]['_id']
    return resultz

if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
