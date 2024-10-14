from app.models import Meeting

MEETING_CONTENT_TEMPLATES = {
    Meeting.TYPE_SUPPORT: """
Hi {contact_first_name},

Thanks for booking a call with TutorCruncher!

Please feel free to jot down a few specific questions to discuss with us beforehand, we would really appreciate it. We \
usually find that the most productive conversations are ones in which we can address specific concerns.

In the meantime, you might find it valuable to glance through some of our documentation which we have prepared to help \
get people familiar with TutorCruncher.

<a href="https://www.youtube.com/watch?v=2iUK0RTm4pw" target="_blank">Guided product demo.</a> 

This guide should cover most initial questions:

<a href="https://cdn.tutorcruncher.com/guides/admin-user-guide.pdf" target="_blank">Admin user guide.</a>

If you haven't signed up yet, \
<a href="https://secure.tutorcruncher.com/start/1/?cli_id={tc2_cligency_id}&tc_source=call_booker">click here to start \
your two week free trial now</a>. You won't have to enter any payment details, and we find our demo is most effective \
when you have had a chance to play around with the system first.

We look forward to connecting!

Best,
The TutorCruncher Team

<a href="{tc2_cligency_url}" target="_blank">Link for TC</a>
""",
    Meeting.TYPE_SALES: """
Hi {contact_first_name},

Thanks for booking a call with TutorCruncher! We're looking forward to hearing all about your business and how we can \
help.

This calendar invitation has a link to a Google Meets room, you can simply join that when the time comes.

Please feel free to jot down a few specific questions to discuss with us beforehand, we would really appreciate it. We \
usually find that the most productive conversations are ones in which we can address specific concerns.

In the meantime, you might find it valuable to glance through some of our documentation which we have prepared to help \
get people familiar with TutorCruncher.

<a href="https://www.youtube.com/watch?v=2iUK0RTm4pw" target="_blank">Guided product demo.</a> 

This guide should cover most initial questions:

<a href="https://cdn.tutorcruncher.com/guides/admin-user-guide.pdf" target="_blank">Admin user guide.</a>

If you haven't signed up yet, \
<a href="https://secure.tutorcruncher.com/start/1/?cli_id={tc2_cligency_id}&tc_source=call_booker" target="_blank">\
click here to start your two week free trial now</a>. You won't have to enter any payment details, and we find our \
demo is most effective when you have had a chance to play around with the system first.

We look forward to hearing about your business!

Best,
The TutorCruncher Team

---

Details for TutorCruncher team:

- Company Name: {company_name}
- Email: {contact_email}
- Phone: {contact_phone}
- Estimated Monthly Revenue: {company_estimated_monthly_revenue}
- Country: {company_country}
- CRM URL: {crm_url}
- TC URL: {tc2_cligency_url}
""",
}
