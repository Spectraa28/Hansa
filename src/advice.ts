// What to do about a refusal from the API, where the message alone doesn't say.
export function advice(message: string): string {
  if (/beyond the sandbox for now/i.test(message)) return 'Hansa can run agents with light, pure-Python dependencies today. Import a folder that holds just the agent, or trim these packages from the requirements file on a branch and import that.'
  if (/no prebuilt Python 3\.12 package/i.test(message)) return 'Check that every dependency installs on Python 3.12 with plain pip, with no compiler needed.'
  if (/500 MB or 200 packages/i.test(message)) return 'Trim the requirements file to what the agent itself needs, then import again.'
  if (/Python constraint/i.test(message)) return 'In step 1, set Python version to 3.12 or a range that includes it, such as >=3.10. Save, then start again.'
  if (/Confirm configuration/i.test(message)) return 'Save the settings in step 1 first.'
  if (/budget|spend limit/i.test(message)) return 'Raise the spend cap and start again.'
  if (/already running|in progress|busy/i.test(message)) return 'Another job is still running. Wait for it to finish, then try again.'
  if (/adapter/i.test(message)) return 'Finish onboarding in the Setup step first.'
  if (/contract/i.test(message)) return 'Save and confirm your tasks in the Setup step first.'
  return ''
}
