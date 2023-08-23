# Actions for Hermes V2

Listed below are all of the actions that can happen and their desired results. When testing the system, all of these actions must be run.

## Actions inside Pipedrive

We have two systems to update when something happens inside Pipedrive: Hermes and TC2. The further expected actions that should happen are denoted by the following:
Bear in mind below that for many actions we receive multiple webhooks. For example, creating a PDDeal with a new Org and Person will mean we get webhooks for each of those objects. 
I'm not sure what order we'll get these webhooks in so hopefully we manage to deal with them in a sensible way. This could cause a potential issue. Taking the above scenario as an example, the the PDDeal webhook will contain an Org id that won't link to any Company inside Hermes. Then we get the webhook for the Company, but it's too late and the deal has not been created.

The solution I'm recommending for the moment is that we make sure the team create an Org, then create any Persons and PDDeals. A more long term solution might be that, if a webhook comes in with an Org id not in our db, we do a request to Pipedrive for the Org details and do a `get_or_create` on them.

* Org created [`_process_pd_organisation`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_organisation)
  * In Hermes:
    * Company object:
      * [x] If it exists, update it with the `pd_org_id` and any other details (`salesperson` etc). **TODO: Currently we're only matching on `pd_org_id` so a new Company will always be created. See TODO in `_process_pd_organisation`.**
      * [x] If it doesn't exist, create it. Assign the `owner` as `salesperson`.
  * In TC2 (only valid if the Company exists in Hermes):
    * Cligency object:
      * [ ] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it with the `pipedrive_url` and `pipedrive_id`.
      * [ ] If it doesn't exist, do nothing.
* Org updated [`_process_pd_organisation`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_organisation)
  * In Hermes:
    * Company object:
      * [ ] If it exists, update it with the `pd_org_id` and any other details (`salesperson` etc).
      * [ ] If it doesn't exist, create it. Assign the `owner` as `salesperson`.
  * In TC2 (only valid if the Company exists in Hermes):
    * Cligency object:
      * [ ] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it with the `pipedrive_url` and `pipedrive_id`.
      * [ ] If it doesn't exist, do nothing.
* Org deleted [`_process_pd_organisation`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_organisation)
  * In Hermes:
    * Company object:
      * [ ] If it exists, delete it.
      * [ ] If it doesn't exist, do nothing.
    * Contact object (only if Company exists):
      * [ ] Delete them.
    * Deal objects (only if Company exists):
      * [ ] Delete them.
    * Meeting objects (only if Contacts exist):
      * [ ] Delete them.
  * In TC2:
    * Cligency object:
      * [ ] If it exists, do nothing.
      * [ ] If it doens't exist, do nothing.
* Person created [`_process_pd_person`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_person)
  * In Hermes:
    * Contact object:
      * [ ] If it exists, update it with the `pd_person_id` and any other details. **TODO: Currently we're only matching on `pd_person_id` so a new Contact will always be created. See TODO in `_process_pd_person`.**
      * [ ] If it doesn't exist and an Org is included in the data, create it.
      * [ ] If it doesn't exist and an Org is not included in the data, ignore it.
  * In TC2:
    * Cligency object:
      * [ ] Do nothing.
* Person updated [`_process_pd_person`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_person)
  * In Hermes:
    * Contact object:
      * [ ] If it exists, update it with relevant details. 
      * [ ] If it doesn't exist and an Org is not included in the data, ignore it.
  * In TC2:
    * Cligency object:
      * [ ] Do nothing.
* Person deleted [`_process_pd_person`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_person)
  * In Hermes:
    * Contact object:
      * [ ] If it exists, delete it.
      * [ ] If it doesn't exist, do nothing.
  * In TC2:
    * Cligency object:
      * [ ] Do nothing.
* PDDeal created [`_process_pd_deal`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_deal)
  * In Hermes:
    * Deal object
      * [ ] If it exists, update it. **Matching on `pd_deal_id` so not really possible. A new Deal would be created.**
      * [ ] If it doesn't exist and the `org_id` doesn't match a Company, do nothing.
      * [ ] If it doesn't exist and the `org_id` does match a Company, create it.
      * [ ] If the data's `person_id` matches a Contact, add them to the Deal
      * [ ] If the data's `person_id` doesn't match a Contact that field is blank.
      * [ ] If the data's `stage_id` matches a Stage, add them to the Deal
      * [ ] If the data's `stage_id` doesn't match a Stage that field is blank.
  * In TC2:
    * Cligency object:
      * [ ] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it with the `pipedrive_deal_stage`, `pipedrive_pipeline`.
      * [ ] If it doesn't exist, do nothing.
* PDDeal updated [`_process_pd_deal`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_deal)
  * In Hermes:
    * Deal object
      * [ ] If it exists, update it.
      * [ ] If it doesn't exist and the `org_id` doesn't match a Company, do nothing.
      * [ ] If it doesn't exist and the `org_id` does match a Company, create it.
      * [ ] If the data's `person_id` matches a Contact, add them to the Deal
      * [ ] If the data's `person_id` doesn't match a Contact that field is blank.
      * [ ] If the data's `stage_id` matches a Stage, add them to the Deal
      * [ ] If the data's `stage_id` doesn't match a Stage that field is blank.
  * In TC2:
    * Cligency object:
      * [ ] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it with the `pipedrive_deal_stage`, `pipedrive_pipeline`.
      * [ ] If it doesn't exist, do nothing.
* PDDeal deleted [`_process_pd_deal`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_deal)
  * In Hermes:
    * Deal object
      * [ ] If it exists, delete it.
      * [ ] If it doesn't exist, do nothing.
      * [ ] Any linked Company will not be affected.
      * [ ] Any linked Contact will not be affected.
      * [ ] Any linked Meeting will not be affected.
      * [ ] Any linked Company will not be affected.
  * In TC2:
    * Cligency object:
      * [ ] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it by setting `pipedrive_deal_stage`, `pipedrive_pipeline` to null.
      * [ ] If it doesn't exist, do nothing.
* PDPipeline created [`_process_pd_pipeline`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_pipeline)
  * In Hermes:
    * [ ] If it doesn't exist, create it.
    * [ ] If it exists, update it.
* PDPipeline updted [`_process_pd_pipeline`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_pipeline)
  * In Hermes:
    * [ ] If it doesn't exist, create it.
    * [ ] If it exists, update it.
* PDPipeline deleted [`_process_pd_pipeline`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_pipeline)
  * In Hermes:
    * [ ] If it doesn't exist, do nothing.
    * [ ] If it exists, delete it.
* PDStage created [`_process_pd_stage`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_stage)
  * In Hermes:
    * [ ] If it doesn't exist, create it.
    * [ ] If it exists, update it.
* PDStage updted [`_process_pd_stage`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_stage)
  * In Hermes:
    * [ ] If it doesn't exist, create it.
    * [ ] If it exists, update it.
* PDStage deleted [`_process_pd_stage`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_stage)
  * In Hermes:
    * [ ] If it doesn't exist, do nothing.
    * [ ] If it exists, delete it.

## Actions from the Callbooker

There are two types of call here, a sales call or a support call.
* Sales call booked [`sales_call`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/callbooker/views.py#:~:text=sales_call)
  * In Hermes:
    * Company object:
      * [ ] If it doesn't exist, create it (Matching on contact.email or company.name). Assign owner from admin.
      * [ ] If it exists, do nothing
    * Contact object:
      * [ ] If it doesn't exist, create it (Matching on contact.email or company.name)
      * [ ] If it exists, do nothing
    * Deal object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists, do nothing
    * Meeting object:
       * [ ] If one exists for the Contact within 2 hours, don't create it
       * [ ] If one cannot be created because the admin is bsuy, don't create it
       * [ ] Else create it
  *  [ ] In Pipedrive
    * Org object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists and the info is different, update it
      * [ ] If it exists and the info is the same, do nothing
    * Person object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists and the info is different, update it
      * [ ] If it exists and the info is the same, do nothing
    * PDDeal object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists, do nothing
    * Activity object:
      * [ ] If the Meeting was created in Hermes, create it
* Support call booked [`support_call`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/callbooker/views.py#:~:text=support_call)
  * In Hermes:
    * Company object:
      * [ ] If it doesn't exist, create it (Matching on contact.email or company.name)
      * [ ] If it exists, do nothing
    * Contact object:
      * [ ] If it doesn't exist, create it (Matching on contact.email or company.name)
      * [ ] If it exists, do nothing
    * Deal object:
      * [ ] Do nothing
    * Meeting object:
       * [ ] If one exists for the Contact within 2 hours, don't create it
       * [ ] If one cannot be created because the admin is bsuy, don't create it
       * [ ] Else create it
  * In Pipedrive
    * Org object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists and the info is different, update it
      * [ ] If it exists and the info is the same, do nothing
    * Person object:
      * [ ] If it doesn't exist, create it
      * [ ] If it exists and the info is different, update it
      * [ ] If it exists and the info is the same, do nothing
    * PDDeal object:
      * [ ] Do nothing
    * Activity object:
      * [ ] If the Meeting was created in Hermes, create it

## Cligency actions

* Cligency created [`update_from_client_event`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/tc2/_process_.py#:~:text=update_from_client_event)
  * In Hermes:
    * Company object:
      * [ ] If it exists, update them with the various `tc2_` fields. **TODO: Currently we're only matching on `tc2_agency_id` so a new Company will always be created. See TODO in `_create_or_update_company`.**
      * [ ] If it doesn't exist, create them.
    * Contact object:
      * [ ] If exists, update them with the various `tc2_` fields. **TODO: Currently we're only matching on `tc2_sr_id` so a new Contact will always be created. See TODO in `_create_or_update_contact`.**
      * [ ] If it doesn't exist, create them.
  * In Pipedrive:
    * Org object:
      * [ ] If it exists, update with the `tc2_` fields.
      * [ ] If it doesn't exist, create it (make sure the owner is assigned).
    * Person object:
      * [ ] If it exists, update it with the `tc2_fields`.
      * [ ] If it doesn't exist, create it.
* Cligency updated [`update_from_client_event`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/tc2/_process_.py#:~:text=update_from_client_event)
  * In Hermes:
    * Company object:
      * [ ] If it exists, update them with the various `tc2_` fields.
      * [ ] If it doesn't exist, create them.
    * Contact object:
      * [ ] If exists, update them with the various `tc2_` fields.
      * [ ] If it doesn't exist, create them.
  * In Pipedrive:
    * Org object:
      * [ ] If it exists, update with the `tc2_` fields.
      * [ ] If it doesn't exist, create it (make sure the owner is assigned).
    * Person object:
      * [ ] If it exists, update it with the `tc2_fields`.
      * [ ] If it doesn't exist, create it.
* Cligency deleted [`update_from_client_event`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/tc2/_process_.py#:~:text=update_from_client_event)
  * In Hermes:
    * Company object:
      * [ ] If it exists, delete it.
      * [ ] If it doesn't exist, do nothing.
    * Contact object:
      * [ ] If it exists, delete it.
      * [ ] If it doesn't exist, do nothing.
  * In Pipedrive:
    * Org object:
      * [ ] Do nothing.
    * Person object:
      * [ ] Do nothing.

# TODO: 

* [ ] If a company is changed in TC to have it's PD org ID set, then it should be linked to the company in PD
* [ ] Deal with merging Orgs/Persons.
