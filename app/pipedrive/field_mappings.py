"""
Pipedrive field mappings - centralized mapping of Hermes field names to Pipedrive custom field IDs.

This single source of truth is used for both:
1. Building Pydantic models with validation_alias (incoming webhooks)
2. Mapping data to send to Pipedrive (outgoing sync)
"""

# Maps Company field names to Pipedrive organization custom field IDs
COMPANY_PD_FIELD_MAP = {
    'hermes_id': '7f8959760703808f36b3795c15310566b74f5134',
    'paid_invoice_count': '70527310be44839c869854b055788a69ecbbab66',
    'tc2_cligency_url': 'd8b615ce8885544ed228feaae3ce9f28dcf04531',
    'tc2_status': '57170eb130b8fa45925381623c86011e4e598e21',
    'website': '770b2fee9c89906b60a74057719509e087342ae9',
    'price_plan': '45f62b0fc120d201ea02fdfa5e7282273add2f20',
    'estimated_income': 'dbe81f3fdf69ce3dfbfc7609caee68f1654c901a',
    'support_person_id': '5ce5a41297410f570d97d78341aa2fbcf5801012',
    'bdr_person_id': 'bdef8d12d2f2af6a61e907b6296e410fdfbef9e3',
    'signup_questionnaire': 'd4db234b06f753a951c0de94456740f270e0f2ed',
    'utm_source': 'd30bf32a173cdfa780901d5eeb92a8f2d1ccd980',
    'utm_campaign': '4be5bf6e60e2a01e2653532e872cd15b5308da23',
    'created': '02ccf8be2c19db0d88f46b9fac20982f43cf1394',
    'pay0_dt': '8ca7c3d5c4d2a343ddfbca712606e27ad9714188',
    'pay1_dt': '291ac593816f0a5ab018f61905274312008c8c9b',
    'pay3_dt': 'cbf504c7cbfad769a3c694de95af60759d6476fc',
    'gclid': '338a35e5195b0d58d3e066cde3b9c45db1a6ac3d',
    'gclid_expiry_dt': '21685501a4a4fc347f609adcafc9908d774034f9',
    'email_confirmed_dt': '35d6e7ef145f1966d2a53fe7c02c87efd1455587',
    'card_saved_dt': '90af5597493bd9a2a0637df22fb29038cbb2a2db',
}

# Maps Deal field names to Pipedrive deal custom field IDs
DEAL_PD_FIELD_MAP = {
    'hermes_id': '5be1188db52a8c7f0ea49331eb391ae54aeabafc',
    'support_person_id': '6911e0b7f9c56a40931381aa0485f705794f6c9f',
    'tc2_cligency_url': '14256b4f62c1dabb53f3e9516c6cc6e23d3aa0af',
    'signup_questionnaire': '1c68afb8974133b7f9d0c30fdbf1d39de2255399',
    'utm_campaign': '268c0a64eb380daf58f15db7e33ead84d06becfe',
    'utm_source': 'b0cf54987b07634053a9e0910fa5ed3d7431d2bf',
    'bdr_person_id': '6dbf5b5aeb23eef43b3bba6cf527b575e970b177',
    'paid_invoice_count': 'ad43be84de47f5cb80084330956fefc529ba3b00',
    'tc2_status': '8b9629376cb523459fbb8eb947190f2663a146dd',
    'website': '54c7fbdf915c9a8fd73dde335942cc72ebea9b9e',
    'price_plan': '44da5d07ad9eebd7f778dcdaf3eee6a0ab4b2e5e',
    'estimated_income': 'b9276dc6ee42b790c98bffed47b539f25ce3ee1c',
}

# Maps Contact field names to Pipedrive person custom field IDs
CONTACT_PD_FIELD_MAP = {
    'hermes_id': '8c2f326b6be255cd3d5cf4ee7385eaf544a47f1d',
}
