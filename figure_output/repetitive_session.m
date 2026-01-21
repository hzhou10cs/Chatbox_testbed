%% Line Plot: Redundant Rate vs # of Session (MATLAB R2025a)
% Three series, each has 5 values.
y1 = [0.10 0.20 0.35 0.40 0.55];   % TODO: replace with your 1st series (1x5)
y2 = [0.12 0.25 0.30 0.42 0.50];   % TODO: replace with your 2nd series (1x5)
y3 = [0.08 0.18 0.28 0.33 0.45];   % TODO: replace with your 3rd series (1x5)

nSessions = 5;
xlsxFiles = {'eval_results/eval_repetitive_mode1/results.xlsx',
    'eval_results/eval_repetitive_mode1/results.xlsx',
    'eval_results/eval_repetitive_mode2/results.xlsx'};  % TODO: replace with your 3 files
seriesNames = {'Benchmark A','Benchmark B','Benchmark C'};

% -------------------- LOAD DATA -----------------------
y1 = load_redundancy_series(xlsxFiles{1}, nSessions);
y2 = load_redundancy_series(xlsxFiles{2}, nSessions);
y3 = load_redundancy_series(xlsxFiles{3}, nSessions);

% Basic validation
assert(isvector(y1) && numel(y1)==5, 'y1 must be a 1x5 vector.');
assert(isvector(y2) && numel(y2)==5, 'y2 must be a 1x5 vector.');
assert(isvector(y3) && numel(y3)==5, 'y3 must be a 1x5 vector.');

x = 1:nSessions;

% Colors aligned to the style seen in the sample .fig files
cBlue   = [0.0353, 0.5176, 0.8902];
cRed  = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];

% Typography (matching the sample style)
fontName       = 'Helvetica';
axFontSize     = 16;
labelFontSize  = 17.6;
legFontSize    = 16;

% Create figure and axes
fig = figure('Color','w','Position',[100 100 1000 420]);
ax  = axes(fig);
hold(ax, 'on');  % Keep all lines on the same axes

% Plot all three lines in ONE call (guarantees 3 lines exist)
Y = [y1(:), y2(:), y3(:)];  % 5x3
h = plot(ax, x, Y, '-', 'LineWidth', 3);

% Apply line colors explicitly
h(1).Color = cBlue;
h(2).Color = cRed;
h(3).Color = cOrange;

% Axes, grid, and limits
grid(ax, 'on');
box(ax, 'off');

xlim(ax, [1 5]);
ylim(ax, [0 0.2]);

xticks(ax, 1:5);
yticks(ax, 0:0.2:1);

% Labels (bold)
xlabel(ax, '# of Session', 'FontName', fontName, 'FontSize', labelFontSize, 'FontWeight', 'bold');
ylabel(ax, 'Redundant Rate', 'FontName', fontName, 'FontSize', labelFontSize, 'FontWeight', 'bold');

% Tick labels + axes styling (bold)
set(ax, ...
    'FontName',   fontName, ...
    'FontSize',   axFontSize, ...
    'FontWeight', 'bold', ...
    'LineWidth',  1);

% Legend (bold)
leg = legend(ax, {'Method 1','Method 2','Method 3'}, ...
    'Location','north', 'Orientation','horizontal');
set(leg, ...
    'Box',        'on', ...
    'FontName',   fontName, ...
    'FontSize',   legFontSize, ...
    'FontWeight', 'bold');

% Optional: export
% exportgraphics(fig, 'redundant_rate.pdf', 'ContentType', 'vector');
% exportgraphics(fig, 'redundant_rate.png', 'Resolution', 300);


%% -------------------- LOCAL FUNCTION --------------------
function y = load_redundancy_series(xlsxPath, nSessions)
%LOAD_REDUNDANCY_SERIES Read one results.xlsx and return 1xnSessions mean redundancy_rate by session_id.

    assert(isfile(xlsxPath), 'Excel file not found: %s', xlsxPath);

    T = readtable(xlsxPath, 'VariableNamingRule','preserve');
    vars = T.Properties.VariableNames;

    % Required columns
    assert(ismember('session_id', vars), 'Missing column "session_id" in %s', xlsxPath);
    assert(ismember('redundancy_rate', vars), 'Missing column "redundancy_rate" in %s', xlsxPath);

    session_id = T.('session_id');
    rate       = T.('redundancy_rate');

    % Base validity
    valid = ~ismissing(session_id) & ~ismissing(rate) & isfinite(rate);

    % Optional: keep only successful rows if status_code exists
    if ismember('status_code', vars)
        sc = T.('status_code');
        valid = valid & ~ismissing(sc) & (sc == 200);
    end

    % Optional: drop parse_error rows if parse_error exists
    if ismember('parse_error', vars)
        pe = T.('parse_error');
        okParse = true(height(T),1);

        if iscell(pe)
            okParse = cellfun(@(x) isempty(x) || (ischar(x) && isempty(strtrim(x))) || (isstring(x) && strlength(x)==0), pe);
        elseif isstring(pe)
            okParse = ismissing(pe) | (strlength(pe)==0);
        elseif ischar(pe)
            okParse = repmat(isempty(strtrim(pe)), height(T), 1);
        end

        valid = valid & okParse;
    end

    % Aggregate by session_id
    sid = session_id(valid);
    rr  = rate(valid);

    % Ensure numeric session ids
    sid = double(sid);

    [G, sidList] = findgroups(sid);
    meanRate = splitapply(@mean, rr, G);

    % Fill output vector (1..nSessions), missing -> NaN
    y = NaN(1, nSessions);
    for i = 1:numel(sidList)
        s = sidList(i);
        if s >= 1 && s <= nSessions
            y(1, s) = meanRate(i);
        end
    end
end