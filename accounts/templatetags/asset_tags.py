"""{% asset 'css/style.css' %} -> /static/css/style.css?v=1731900000

Adds the file's last-changed time, so phones and browsers fetch the new version
after every update instead of using an old cached copy. Load with {% load asset_tags %}.
"""

import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def asset(path):
    url = static(path)
    found = finders.find(path)
    if found:
        url += f"?v={int(os.path.getmtime(found))}"
    return url
