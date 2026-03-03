# Trigger

Performances in the admin UI started to slow. I added a profilter in the debug why :
It was just too much UI, too much module

# Solution 
Add a lazy loader of admin tabs.
cf : render_admin_tabs_lazy and segmented_control because tabs cannot support lazzy loading.
