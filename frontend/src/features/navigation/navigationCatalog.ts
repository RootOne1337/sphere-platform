import {
    Activity,
    Code2,
    FileText,
    FolderOpen,
    Gamepad2,
    GitBranch,
    History,
    LayoutDashboard,
    ListTodo,
    MapPin,
    Monitor,
    Radar,
    RefreshCw,
    ScrollText,
    Settings2,
    ToggleRight,
    Users,
    UserCog,
    Webhook,
    Wifi,
    Zap,
} from "lucide-react";

export const SPHERE_NAV_GROUPS = [
    {
        label: "Обзор",
        items: [
            { href: "/dashboard", label: "Главная", icon: LayoutDashboard },
            { href: "/monitoring", label: "Инфраструктура", icon: Activity },
        ],
    },
    {
        label: "Устройства",
        items: [
            { href: "/devices", label: "Парк устройств", icon: Monitor },
            { href: "/stream", label: "Видеопоток", icon: Monitor },
            { href: "/discovery", label: "Обнаружение", icon: Radar },
            { href: "/groups", label: "Группы", icon: FolderOpen },
            { href: "/locations", label: "Локации", icon: MapPin },
        ],
    },
    {
        label: "Автоматизация",
        items: [
            { href: "/tasks", label: "Задания", icon: ListTodo },
            { href: "/orchestration", label: "Оркестрация", icon: GitBranch },
            { href: "/pipeline-settings", label: "Пайплайны", icon: Settings2 },
            { href: "/accounts", label: "Игровые аккаунты", icon: Gamepad2 },
            { href: "/scripts", label: "Скрипты", icon: Code2 },
        ],
    },
    {
        label: "События и сеть",
        items: [
            { href: "/events", label: "События устройств", icon: Zap },
            { href: "/event-triggers", label: "Триггеры событий", icon: ToggleRight },
            { href: "/sessions", label: "Сессии", icon: History },
            { href: "/vpn", label: "Туннели и VPN", icon: Wifi },
            { href: "/webhooks", label: "Вебхуки", icon: Webhook },
        ],
    },
    {
        label: "Администрирование",
        items: [
            { href: "/users", label: "Пользователи", icon: Users },
            { href: "/audit", label: "Журнал аудита", icon: ScrollText },
            { href: "/logs", label: "Системные логи", icon: FileText },
            { href: "/updates", label: "Обновления", icon: RefreshCw },
            { href: "/settings", label: "Конфигурация", icon: UserCog },
        ],
    },
];
