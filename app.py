import addict
import yaml
from flask import Flask, render_template, request, url_for, flash, redirect
from BookBuilder import grower_run

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cromptinator'


with open('./config.yaml', 'w') as f:
    bb_default_config = addict.Dict(yaml.safe_load(f))


messages = [{'title': 'Message One',
             'content': 'Message One Content'},
            {'title': 'Message Two',
             'content': 'Message Two Content'}
            ]

@app.route('/', methods=('GET', 'POST'))
def index():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']

        if not title:
            flash('Title is required!')
        elif not content:
            flash('Content is required!')
        else:
            messages.append({'title': title, 'content': content})
            grower_run()

            return redirect(url_for('index'))
        return render_template('index.html', messages=messages)

    return render_template('index.html', messages=messages)
