import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { ArrowRight, FolderOpen, GitBranch, Lock, Search } from 'lucide-react'
import { api, ApiError, send } from './api'
import type { Session } from './api'

type Connection = { configured: boolean; status: string; github_login: string | null }
type Installations = { installations: { id: number; account: string }[]; installation_url: string }
type Repo = { id: number; full_name: string; default_branch: string | null; private: boolean }
type Branches = { repository: Repo; branches: { name: string; commit_sha: string }[] }

const message = (error: unknown) => error instanceof ApiError ? error.message : 'Could not reach Hansa. Check your connection and try again.'

export default function NewImport({ session }: { session: UseQueryResult<Session | null, Error> }) {
  const navigate = useNavigate()
  const user = session.data?.user.id
  const [installation, setInstallation] = useState<number | null>(null)
  const [repo, setRepo] = useState<Repo | null>(null)
  const [branch, setBranch] = useState('')
  const [folder, setFolder] = useState('')
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const connection = useQuery({ queryKey: ['github', user], enabled: Boolean(user), queryFn: ({ signal }) => api<Connection>('/github/connection', { signal }) })
  const connected = connection.data?.status === 'connected'
  const installs = useQuery({ queryKey: ['installations', user], enabled: connected, queryFn: ({ signal }) => api<Installations>('/github/installations?per_page=100', { signal }) })
  const account = installation ?? installs.data?.installations[0]?.id ?? null
  const repos = useQuery({ queryKey: ['repos', user, account], enabled: account != null, queryFn: ({ signal }) => api<{ repositories: Repo[]; has_next: boolean }>(`/github/repositories?installation_id=${account}&per_page=100`, { signal }) })
  const branches = useQuery({ queryKey: ['branches', user, account, repo?.id], enabled: account != null && repo != null, queryFn: ({ signal }) => api<Branches>(`/github/branches?installation_id=${account}&repository_id=${repo!.id}&per_page=100`, { signal }) })

  const chosen = branch || repo?.default_branch || branches.data?.branches[0]?.name || ''
  const folders = useQuery({ queryKey: ['folders', user, account, repo?.id, chosen], enabled: account != null && repo != null && Boolean(chosen), retry: false,
    queryFn: ({ signal }) => api<{ folders: string[] }>(`/github/folders?installation_id=${account}&repository_id=${repo!.id}&branch=${encodeURIComponent(chosen)}`, { signal }) })
  if (session.isSuccess && !session.data) return <Navigate to="/sign-in" replace />

  async function connect() {
    setBusy(true); setError('')
    try { window.location.assign((await send<{ authorization_url: string }>('/github/connect', session.data!.csrf_token)).authorization_url) }
    catch (caught) { setError(message(caught)); setBusy(false) }
  }
  async function start() {
    if (!repo || account == null || !chosen) return
    setBusy(true); setError('')
    try {
      const created = await send<{ id: string }>('/github/imports', session.data!.csrf_token, { installation_id: account, repository_id: repo.id, branch: chosen, ...(folder.trim() ? { folder: folder.trim().replace(/^\/+|\/+$/g, '') } : {}) })
      navigate(`/app/imports/${created.id}?step=import`)
    } catch (caught) { setError(message(caught)); setBusy(false) }
  }

  const shown = repos.data?.repositories.filter(item => item.full_name.toLowerCase().includes(filter.trim().toLowerCase())) || []
  return <main className="page max-w-4xl">
    <Link to="/app" className="back-link">← your agents</Link>
    <h1 className="page-title mt-2">Bring an agent.</h1>
    <p className="mt-4 max-w-[52ch] text-[17px] text-muted">Pick the repository your agent lives in. Hansa copies one commit, read-only. Nothing runs until you say so.</p>

    <section className="workflow-guide mt-8 rounded-control p-5 sm:p-6" aria-labelledby="import-guide">
      <details>
        <summary className="min-h-11 cursor-pointer py-2"><h2 id="import-guide" className="inline font-display text-[22px] font-semibold">How to import your agent</h2></summary>
        <ol className="mt-6 grid gap-8 lg:grid-cols-3">
        <li><h3 className="font-semibold">1. Connect GitHub</h3><p className="mt-2 text-muted">Connect your account and give the Hansa GitHub App access to the repository. If it is missing from the list, use the grant access link.</p></li>
        <li><h3 className="font-semibold">2. Choose the source</h3><p className="mt-2 text-muted">Select your repository and branch. Import the whole repo, or choose the agent’s folder. Use the whole repo if the agent needs files outside that folder.</p></li>
        <li><h3 className="font-semibold">3. Start the import</h3><p className="mt-2 text-muted">Click Import this repo or the selected folder’s import button. Hansa queues the source copy and opens the agent’s page, where you can follow its status.</p></li>
        </ol>
      </details>
    </section>

    {connection.isPending || session.isPending ? <p role="status" className="mt-10">Checking your GitHub connection…</p>
      : connection.isError ? <div role="alert" className="mt-10"><p>{message(connection.error)}</p><button className="button-secondary mt-4" onClick={() => void connection.refetch()}>Try again</button></div>
      : !connection.data?.configured ? <p className="slab mt-10 p-8">GitHub import isn't configured on this server yet.</p>
      : !connected ? <section className="slab mt-10 p-8 pt-9"><span className="slab-tab">step 1</span>
        <h2 className="font-display text-[30px] leading-none font-medium">Connect GitHub.</h2>
        <p className="mt-3 max-w-[54ch] text-muted">Hansa asks for read access to code and metadata only, and only on the repositories you choose.</p>
        <button className="button-primary mt-6 min-h-14 text-[16px]" disabled={busy} onClick={() => void connect()}><GitBranch size={20} aria-hidden="true" /> {busy ? 'Opening GitHub…' : 'Connect GitHub'}</button>
      </section>
      : <>
        <section className="slab mt-10 p-6 pt-8 sm:p-8 sm:pt-9"><span className="slab-tab">1 · pick a repo</span>
          <div className="flex flex-wrap items-center gap-3">
            {(installs.data?.installations.length || 0) > 1 && <select aria-label="GitHub account" className="field w-auto" value={account ?? ''} onChange={event => { setInstallation(Number(event.target.value)); setRepo(null); setBranch('') }}>{installs.data!.installations.map(item => <option key={item.id} value={item.id}>{item.account}</option>)}</select>}
            <label className="relative min-w-[200px] flex-1"><span className="sr-only">Filter repositories</span><Search size={16} aria-hidden="true" className="absolute top-1/2 left-3 -translate-y-1/2 text-muted" /><input className="field pl-9" placeholder="Filter repositories" value={filter} onChange={event => setFilter(event.target.value)} /></label>
            {installs.data && <a href={installs.data.installation_url} className="tabular text-[15px] font-medium link-action">don't see it? grant access</a>}
          </div>
          {installs.isError || repos.isError ? <p role="alert" className="mt-5">{message(installs.error || repos.error)}</p>
            : installs.isPending || (account != null && repos.isPending) ? <p role="status" className="mt-5 text-muted">Loading repositories…</p>
            : account == null ? <p className="mt-5">The Hansa GitHub App isn't installed on any account you can reach. <a className="font-semibold underline" href={installs.data?.installation_url}>Install it on a repository</a>, then come back.</p>
            : shown.length === 0 ? <p className="mt-5 text-muted">{filter ? 'No repository matches that filter.' : 'The app has no repositories yet. Grant access to one.'}</p>
            : <ul className="mt-5 max-h-[340px] divide-y divide-line overflow-y-auto rounded-control border border-line">{shown.map(item => <li key={item.id}>
              <button aria-pressed={repo?.id === item.id} onClick={() => { setRepo(item); setBranch(''); setFolder('') }} className={`flex min-h-12 w-full items-center gap-3 px-4 py-2 text-left tabular text-[14px] transition-colors ${repo?.id === item.id ? 'is-selected' : 'hover:bg-blue-soft'}`}>
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{item.full_name}</span>{item.private && <Lock size={14} aria-label="private" />}</button></li>)}</ul>}
          {repos.data?.has_next && <p className="mt-3 tabular text-[14px] text-muted">Showing the first 100. Use the filter, or limit the app to fewer repositories.</p>}
        </section>

        <section className={`slab mt-9 p-6 pt-8 sm:p-8 sm:pt-9 ${repo ? '' : 'opacity-50'}`}><span className="slab-tab">2 · branch and folder</span>
          {!repo ? <p className="text-muted">Choose a repository first.</p>
            : branches.isError ? <p role="alert">{message(branches.error)}</p>
            : <div className="flex flex-wrap items-end gap-4">
              <label className="min-w-[220px] flex-1 text-[15px] font-medium">Branch of <span className="tabular">{repo.full_name}</span>
                <span className="relative mt-2 block"><GitBranch size={16} aria-hidden="true" className="absolute top-1/2 left-3 -translate-y-1/2" />
                  <select className="field pl-9 tabular" value={chosen} disabled={branches.isPending} onChange={event => { setBranch(event.target.value); setFolder('') }}>{branches.isPending ? <option>{chosen || 'Loading…'}</option> : branches.data.branches.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select></span></label>
            </div>}
          {repo && !branches.isError && <div className="mt-6 pt-5">
            <p className="text-[15px] font-medium">Where does the agent live?</p>
            <p className="mt-1 text-[15px] text-muted">Import the whole repository, or just the folder the agent is in. Pick a folder when the repo also holds a frontend or other apps.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" aria-pressed={!folder} onClick={() => setFolder('')} className={`chip min-h-9 ${!folder ? 'is-selected' : 'bg-surface hover:bg-blue-soft'}`}>whole repo</button>
              {folders.data?.folders.map(name => <button type="button" key={name} aria-pressed={folder === name} onClick={() => setFolder(name)} className={`chip min-h-9 ${folder === name ? 'is-selected' : 'bg-surface hover:bg-blue-soft'}`}><FolderOpen size={13} aria-hidden="true" />{name}</button>)}
              {folders.isPending && chosen && <span className="chip chip-quiet min-h-9">looking for folders…</span>}
            </div>
            <label className="mt-3 block max-w-md text-[15px] font-medium">Or type a path<input className="field mt-2 tabular" placeholder="services/agent" maxLength={200} value={folder} onChange={event => setFolder(event.target.value)} /></label>
            <div className="mt-6">              <button className="button-primary min-h-12 px-7 text-[16px]" disabled={busy || !chosen} onClick={() => void start()}>{busy ? 'Importing…' : folder.trim() ? `Import /${folder.trim().replace(/^\/+|\/+$/g, '')}` : 'Import this repo'} <ArrowRight size={18} aria-hidden="true" /></button></div>
          </div>}
        </section>
      </>}
    {error && <p role="alert" className="mt-6 rounded-control bg-waste px-4 py-3 font-medium">{error}</p>}
    <section className="workflow-guide mt-12 pt-10" aria-labelledby="after-import-guide">
      <h2 id="after-import-guide" className="font-display text-[26px] leading-tight font-semibold">What happens after import?</h2>
      <ol className="mt-8 space-y-8">
        <li><h3 className="font-semibold">A source copy, tied to one commit</h3><p className="mt-2 max-w-[65ch] text-muted">Hansa saves the selected source revision. Importing does not execute your agent or install its dependencies, and your GitHub repository is not changed.</p></li>
        <li><h3 className="font-semibold">Setup before execution</h3><p className="mt-2 max-w-[65ch] text-muted">Once the copy is ready, open Setup to review the detected configuration, model and tool permissions. Start onboarding to prepare and prove the adapter, then review and confirm the tasks and checks for your baseline.</p></li>
        <li><h3 className="font-semibold">Measure, experiment, review</h3><p className="mt-2 max-w-[65ch] text-muted">Start the baseline, inspect suggestions or run an investigation, then choose a change to test. Result shows the comparison and any regressions, with a patch or brief when available.</p></li>
      </ol>
      <p className="guide-note mt-8 max-w-[65ch]">Each stage starts from its own button. Check the spend limit before launching it. You can leave and return through <Link to="/app" className="inline-flex min-h-11 items-center font-semibold text-blue underline underline-offset-4">Your agents</Link>; opening the page does not restart a job.</p>
    </section>
  </main>
}
