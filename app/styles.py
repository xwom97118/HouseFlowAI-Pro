APP_QSS = """
* {
    font-family: "Microsoft JhengHei", "Segoe UI", sans-serif;
    font-size: 14px;
}

QMainWindow,
QWidget {
    background: #F6F8FC;
    color: #172033;
}

#Sidebar {
    background: #0F172A;
    border: none;
}

#Brand {
    color: #FFFFFF;
    font-size: 22px;
    font-weight: 800;
    padding: 20px 16px 18px 16px;
}

#NavButton {
    background: transparent;
    color: #AEBBD0;
    text-align: left;
    padding: 13px 16px;
    border: 0;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 500;
}

#NavButton:hover {
    background: #17233A;
    color: #FFFFFF;
}

#NavButton:checked {
    background: #2563EB;
    color: #FFFFFF;
    font-weight: 700;
}

#Topbar {
    background: #FFFFFF;
    border-bottom: 1px solid #E7ECF3;
}

#PageTitle {
    font-size: 24px;
    font-weight: 800;
    color: #14213D;
}

#Muted,
#MutedLabel {
    color: #718096;
}

#Card,
#DashboardPanel,
#DashboardMetricCard {
    background: #FFFFFF;
    border: 1px solid #E6EBF2;
    border-radius: 16px;
}

#DashboardHero {
    background: #FFFFFF;
    border: 1px solid #E6EBF2;
    border-radius: 18px;
}

#DashboardGreeting {
    color: #172033;
    font-size: 27px;
    font-weight: 800;
}

#DashboardSubtitle {
    color: #718096;
    font-size: 14px;
}

#HeroPrimaryButton {
    background: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 11px;
    padding: 12px 20px;
    font-weight: 700;
    min-height: 20px;
}

#HeroPrimaryButton:hover {
    background: #1D4ED8;
}

#MetricIcon {
    background: #EEF4FF;
    color: #2563EB;
    border-radius: 10px;
    padding: 6px 9px;
    font-size: 17px;
    min-width: 26px;
}

#MetricTitle {
    color: #526176;
    font-size: 14px;
    font-weight: 700;
}

#DashboardMetricValue,
#MetricValue {
    color: #111827;
    font-size: 34px;
    font-weight: 800;
}

#MetricSubtitle {
    color: #8A97A8;
    font-size: 12px;
}

#PanelTitle {
    color: #172033;
    font-size: 18px;
    font-weight: 800;
}

#PanelSubtitle {
    color: #8290A4;
    font-size: 12px;
}

#QuickActionButton {
    background: #F8FAFD;
    color: #24324A;
    text-align: left;
    border: 1px solid #E7ECF3;
    border-radius: 12px;
    padding: 12px 16px;
    font-weight: 700;
}

#QuickActionButton:hover {
    background: #EEF4FF;
    border-color: #BFD2FF;
    color: #1D4ED8;
}

#TaskRow {
    background: #F9FBFE;
    border: 1px solid #E8EDF4;
    border-radius: 12px;
}

#TaskRow:hover {
    background: #F3F7FF;
    border-color: #CAD8F7;
}

#TaskIcon {
    background: #EEF4FF;
    color: #2563EB;
    border-radius: 9px;
    min-width: 34px;
    min-height: 34px;
    font-size: 16px;
}

#TaskTitle {
    color: #24324A;
    font-size: 14px;
    font-weight: 700;
}

#TaskSubtitle {
    color: #8794A7;
    font-size: 12px;
}

#TaskButton {
    background: #FFFFFF;
    color: #2563EB;
    border: 1px solid #C9D8F7;
    border-radius: 9px;
    padding: 7px 12px;
    font-weight: 700;
}

#TaskButton:hover {
    background: #2563EB;
    color: #FFFFFF;
}

#DashboardTip {
    background: #EEF5FF;
    border: 1px solid #D4E3FF;
    border-radius: 12px;
}

#TipTitle {
    color: #1D4ED8;
    font-weight: 800;
}

#TipText {
    color: #52647C;
    font-size: 13px;
}

#PrimaryButton {
    background: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 10px 16px;
    font-weight: 700;
}

#PrimaryButton:hover {
    background: #1D4ED8;
}

#PrimaryButton:disabled {
    background: #A8B8D4;
    color: #EEF2F7;
}

#SecondaryButton {
    background: #FFFFFF;
    color: #40506A;
    border: 1px solid #CBD5E1;
    border-radius: 10px;
    padding: 9px 14px;
    font-weight: 600;
}

#SecondaryButton:hover {
    background: #F4F7FB;
    border-color: #AFC0D7;
}

QLineEdit,
QComboBox,
QTextEdit,
QPlainTextEdit,
QDateEdit,
QTimeEdit {
    background: #FFFFFF;
    color: #172033;
    border: 1px solid #CCD6E3;
    border-radius: 9px;
    padding: 8px 10px;
    selection-background-color: #2563EB;
}

QLineEdit:focus,
QComboBox:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QDateEdit:focus,
QTimeEdit:focus {
    border: 1px solid #4F7FEF;
}

QComboBox::drop-down {
    border: 0;
    width: 28px;
}

QCheckBox {
    color: #334155;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid #B7C4D5;
    background: #FFFFFF;
}

QCheckBox::indicator:checked {
    background: #2563EB;
    border-color: #2563EB;
}

QGroupBox {
    background: #FFFFFF;
    border: 1px solid #E5EAF1;
    border-radius: 13px;
    margin-top: 14px;
    padding-top: 12px;
    font-weight: 700;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: #24324A;
}

QTableWidget {
    background: #FFFFFF;
    alternate-background-color: #FAFCFF;
    color: #24324A;
    border: 1px solid #E3E9F1;
    border-radius: 12px;
    gridline-color: #EDF1F6;
    selection-background-color: #E8F0FF;
    selection-color: #172033;
}

QHeaderView::section {
    background: #F4F7FB;
    color: #526176;
    padding: 10px;
    border: 0;
    border-bottom: 1px solid #E2E8F0;
    font-weight: 700;
}

QScrollArea {
    border: 0;
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #CBD5E1;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #94A3B8;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background: #CBD5E1;
    border-radius: 5px;
    min-width: 30px;
}

QTabWidget::pane {
    border: 1px solid #E4EAF2;
    background: #FFFFFF;
    border-radius: 10px;
}

QTabBar::tab {
    padding: 10px 16px;
    background: #EFF3F8;
    color: #65758A;
    margin-right: 3px;
    border-radius: 8px 8px 0 0;
}

QTabBar::tab:selected {
    background: #FFFFFF;
    color: #2563EB;
    font-weight: 700;
}

QMessageBox {
    background: #FFFFFF;
}

QToolTip {
    background: #172033;
    color: #FFFFFF;
    border: 0;
    padding: 6px 8px;
}

#SectionTitleLabel {
    font-size: 20px;
    font-weight: 800;
    color: #14213D;
}

#StepBadge {
    background: #2563EB;
    color: #FFFFFF;
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 12px;
    font-weight: 800;
    max-width: 60px;
}

#StepTitle {
    color: #172033;
    font-size: 16px;
    font-weight: 800;
}

#CtaBar {
    background: #FFFFFF;
    border-top: 1px solid #E6EBF2;
}

#SuccessButton {
    background: #16A34A;
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 10px 16px;
    font-weight: 700;
}

#SuccessButton:hover {
    background: #15803D;
}

#SuccessButton:disabled {
    background: #A7D8BC;
    color: #F0FBF4;
}

#DangerButton {
    background: #DC2626;
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 10px 16px;
    font-weight: 700;
}

#DangerButton:hover {
    background: #B91C1C;
}

#PropertyThumb {
    background: #EEF2F8;
    border: 1px solid #E1E7F0;
    border-radius: 10px;
    color: #8A97A8;
    font-size: 12px;
}

#PropertyCardTitle {
    font-size: 15px;
    font-weight: 800;
    color: #172033;
}

#SidebarFooter {
    border-top: 1px solid #1F2A44;
}

#SidebarUser {
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 700;
}

#SidebarVersion {
    color: #7C8AA5;
    font-size: 11px;
}

#SidebarStatus {
    color: #34D399;
    font-size: 11px;
    font-weight: 700;
}

#StatusBadge {
    border-radius: 8px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 700;
}

#StatusBadge[kind="success"] { background: #DCFCE7; color: #15803D; }
#StatusBadge[kind="warning"] { background: #FEF3C7; color: #B45309; }
#StatusBadge[kind="danger"]  { background: #FEE2E2; color: #B91C1C; }
#StatusBadge[kind="info"]    { background: #DBEAFE; color: #1D4ED8; }
#StatusBadge[kind="neutral"] { background: #E5E9F0; color: #526176; }
"""