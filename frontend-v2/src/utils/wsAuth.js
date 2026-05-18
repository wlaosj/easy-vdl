export function buildAuthedWsUrl(path) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const token = localStorage.getItem('token')
    const basePath = path.startsWith('/') ? path : `/${path}`
    let url = `${protocol}//${host}${basePath}`

    if (token) {
        const sep = url.includes('?') ? '&' : '?'
        url = `${url}${sep}token=${encodeURIComponent(token)}`
    }

    return url
}
