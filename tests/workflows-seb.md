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
        * When creating the company in pipedrive it must have a tc2_status
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
      * [x] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it with the `pipedrive_url` and `pipedrive_id`.
      * [x] If it doesn't exist, do nothing.
        * 404 Client Error
* Org deleted [`_process_pd_organisation`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_organisation)
  * In Hermes:
    * Company object:
      * [x] If it exists, delete it.
      * [x] If it doesn't exist, do nothing.
    * Contact object (only if Company exists): # Issue #12 https://github.com/tutorcruncher/hermes_v2/issues/15
      * [ ] Delete them.
    * Deal objects (only if Company exists):
      * [x] Delete them.
    * Meeting objects (only if Contacts exist):
      * [ ] Delete them.
  * In TC2:
    * Cligency object:
      * [x] If it exists, do nothing.
      * [x] If it doens't exist, do nothing.
* Person created [`_process_pd_person`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_person)
  * In Hermes:
    * Contact object:
      * [ ] If it exists, update it with the `pd_person_id` and any other details. **TODO: Currently we're only matching on `pd_person_id` so a new Contact will always be created. See TODO in `_process_pd_person`.**
      * [x] If it doesn't exist and an Org is included in the data, create it.
      * [x] If it doesn't exist and an Org is not included in the data, ignore it.
  * In TC2:
    * Cligency object:
      * [x] Do nothing.
* Person updated [`_process_pd_person`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_person)
  * In Hermes:
    * Contact object:
      * [x] If it exists, update it with relevant details.
        * Country not Person Model
      * [x] If it doesn't exist and an Org is not included in the data, ignore it.
  * In TC2:
    * Cligency object:
      * [x] Do nothing.
* Person deleted [`_process_pd_person`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_person)
  * In Hermes:
    * Contact object:
      * [x] If it exists, delete it.
      * [x] If it doesn't exist, do nothing.
  * In TC2:
    * Cligency object:
      * [x] Do nothing.
* PDDeal created [`_process_pd_deal`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_deal)
  * In Hermes:
    * Deal object
      * [x] If it exists, update it. **Matching on `pd_deal_id` so not really possible. A new Deal would be created.**
      * [x] If it doesn't exist and the `org_id` doesn't match a Company, do nothing.
      * [x] If it doesn't exist and the `org_id` does match a Company, create it.
      * [x] If the data's `person_id` matches a Contact, add them to the Deal
      * [ ] If the data's `person_id` doesn't match a Contact that field is blank.
        * If the `person_id` doesnt match a Contact, we create a new Contact. (must be a contact webhook)
      * [x] If the data's `stage_id` matches a Stage, add them to the Deal
      * [ ] If the data's `stage_id` doesn't match a Stage that field is blank.
  * In TC2:
    * Cligency object:
      * [x] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it with the `pipedrive_deal_stage`, `pipedrive_pipeline`.
      * [x] If it doesn't exist, do nothing.
        * 404 Client Error
* PDDeal updated [`_process_pd_deal`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_deal)
  * In Hermes:
    * Deal object
      * [x] If it exists, update it.
      * [x] If it doesn't exist and the `org_id` doesn't match a Company, do nothing.
        * 422 Error Company with pd_org_id 150 does not exist
      * [x] If it doesn't exist and the `org_id` does match a Company, create it.
      * [ ] If the data's `person_id` matches a Contact, add them to the Deal
      * [ ] If the data's `person_id` doesn't match a Contact that field is blank.
      * [x] If the data's `stage_id` matches a Stage, add them to the Deal
      * [x] If the data's `stage_id` doesn't match a Stage that field is blank.
        * 422 Error Stage with pd_stage_id {id} does not exist
  * In TC2:
    * Cligency object:
      * [x] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it with the `pipedrive_deal_stage`, `pipedrive_pipeline`.
      * [x] If it doesn't exist, do nothing.
* PDDeal deleted [`_process_pd_deal`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_deal)
  * In Hermes:
    * Deal object
      * [x] If it exists, delete it.
      * [x] If it doesn't exist, do nothing.
      * [x] Any linked Company will not be affected.
      * [x] Any linked Contact will not be affected.
      * [ ] Any linked Meeting will not be affected.
  * In TC2:
    * Cligency object:
      * [ ] If it exists in TC2 (we know this if the Company has a `tc2_cligency_id`), then update it by setting `pipedrive_deal_stage`, `pipedrive_pipeline` to null.
        * Does not set to null
      * [x] If it doesn't exist, do nothing.
* PDPipeline created [`_process_pd_pipeline`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_pipeline)
  * In Hermes:
    * [x] If it doesn't exist, create it.
    * [x] If it exists, update it.
* PDPipeline updated [`_process_pd_pipeline`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_pipeline)
  * In Hermes:
    * [x] If it doesn't exist, create it.
    * [x] If it exists, update it.
* PDPipeline deleted [`_process_pd_pipeline`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_pipeline)
  * In Hermes:
    * [x] If it doesn't exist, do nothing.
    * [x] If it exists, delete it.
* PDStage created [`_process_pd_stage`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_stage)
  * In Hermes:
    * [x] If it doesn't exist, create it.
    * [x] If it exists, update it.
* PDStage updted [`_process_pd_stage`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_stage)
  * In Hermes:
    * [x] If it doesn't exist, create it.
    * [x] If it exists, update it.
* PDStage deleted [`_process_pd_stage`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/pipedrive/_process.py#:~:text=_process_pd_stage)
  * In Hermes:
    * [x] If it doesn't exist, do nothing.
    * [x] If it exists, delete it.

## Cligency actions

* Cligency created [`update_from_client_event`](https://github.com/tutorcruncher/hermes_v2/blob/main/app/tc2/_process_.py#:~:text=update_from_client_event)
  * In Hermes:
    * Company object:
      * [ ] If it exists, update them with the various `tc2_` fields. **TODO: Currently we're only matching on `tc2_agency_id` so a new Company will always be created. See TODO in `_create_or_update_company`.**
      * [x] If it doesn't exist, create them.
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
