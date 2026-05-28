export { }

declare global {
    interface TelegramMiniAppUser {
        id: number
        first_name: string
        last_name?: string
        username?: string
        photo_url?: string
    }

    interface TelegramWebApp {
        initData: string
        initDataUnsafe?: {
            user?: TelegramMiniAppUser
        }

        ready(): void
        expand(): void

        showAlert(message: string, callback?: () => void): void

        setHeaderColor(color: string): void
        setBackgroundColor(color: string): void
        setBottomBarColor(color: string): void

        isVersionAtLeast(version: string): boolean
        requestFullscreen(): void

        onEvent(
            eventType: string,
            callback: (...args: any[]) => void,
        ): void

        offEvent(
            eventType: string,
            callback: (...args: any[]) => void,
        ): void
    }

    interface Window {
        Telegram?: {
            WebApp: TelegramWebApp
        }
    }
}