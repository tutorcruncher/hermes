from app.models import Meeting

MEETING_CONTENT_TEMPLATES = {
    Meeting.TYPE_SUPPORT: {
        'summary': 'Introduction to TutorCruncher with {admin_name}',
        'description': """
Hi {contact_first_name},

Thanks for booking a call with TutorCruncher! We'll be looking forward to seeing you in the Google Meets room!

Please feel free to jot down a few specific questions to discuss with us beforehand, we would really appreciate it. We \
usually find that the most productive conversations are ones in which we can address specific concerns.

In the meantime, you might find it valuable to glance through some of our documentation which we have prepared to help \
get people familiar with TutorCruncher.

<a href="https://www.youtube.com/watch?v=2iUK0RTm4pw" target="_blank">Guided product demo.</a> 

We also have our user guide for some of our most common questions:

<a href="https://cdn.tutorcruncher.com/guides/admin-user-guide.pdf" target="_blank">Admin user guide.</a>

If you haven't signed up yet, \
<a href="https://secure.tutorcruncher.com/start/1/?cli_id={tc_cligency_id}&tc_source=call_booker">click here to start \
your two week free trial now</a>. You won't have to enter any payment details, and we find our demo is most effective \
when you have had a chance to play around with the system first.

We look forward to hearing about your business!

Best,
The TutorCruncher Team

<a href="{tc_cligency_url}" target="_blank">Link for TC</a>
""",
    },
    Meeting.TYPE_SALES: {
        'summary': 'Introduction to TutorCruncher with {admin_name}',
        'description': """
Hi {contact_first_name},

Thanks for booking a call with TutorCruncher! We're looking forward to hearing all about your business and how we can \
help.

This calendar invitation has a link to a Google Meets room, you can simply join that when the time comes.

Please feel free to jot down a few specific questions to discuss with us beforehand, we would really appreciate it. We \
usually find that the most productive conversations are ones in which we can address specific concerns.

In the meantime, you might find it valuable to glance through some of our documentation which we have prepared to help \
get people familiar with TutorCruncher.

<a href="https://www.youtube.com/watch?v=2iUK0RTm4pw" target="_blank">Guided product demo.</a> 

We also have our user guide for some of our most common questions:

<a href="https://cdn.tutorcruncher.com/guides/admin-user-guide.pdf" target="_blank">Admin user guide.</a>

If you haven't signed up yet, \
<a href="https://secure.tutorcruncher.com/start/1/?cli_id={tc_cligency_id}&tc_source=call_booker" target="_blank">\
click here to start your two week free trial now</a>. You won't have to enter any payment details, and we find our \
demo is most effective when you have had a chance to play around with the system first.

We look forward to hearing about your business!

Best,
The TutorCruncher Team

<a href="{crm_url}" class="smaller" target="_blank">CRM link</a>
<a href="{tc_cligency_url}" class="smaller" target="_blank">TC link</a>
""",
    },
}
